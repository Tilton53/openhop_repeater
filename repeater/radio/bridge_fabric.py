from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from repeater.radio.manager import RadioManager


@dataclass(frozen=True)
class BridgeDecision:
    packet_id: Optional[str]
    is_duplicate: bool
    metadata: Dict[str, Any]
    target_endpoint_ids: List[str]


class RadioBridgeFabric:
    """Bridge metadata and fan-out planning for multi-radio packet flow."""

    def __init__(self, manager: RadioManager, *, dedupe_ttl: float = 30.0):
        self.manager = manager
        self.dedupe_ttl = dedupe_ttl
        self._seen_packets: Dict[str, float] = {}

    def annotate_ingress(
        self,
        packet: Any,
        *,
        origin_radio: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        enriched = dict(metadata or {})
        if origin_radio is not None:
            enriched.setdefault("origin_radio", origin_radio)
            enriched.setdefault("rx_radio", origin_radio)
        enriched.setdefault("bridged", False)
        enriched.setdefault("bridge_tx_targets", [])
        enriched.setdefault("rx_timestamp", time.time())
        packet_id = self.packet_id(packet)
        if packet_id is not None:
            enriched.setdefault("packet_id", packet_id)
        return enriched

    def packet_id(self, packet: Any) -> Optional[str]:
        try:
            value = packet.calculate_packet_hash()
        except Exception:
            return None
        if isinstance(value, bytes):
            return value.hex().upper()
        return str(value)

    def build_decision(
        self,
        packet: Any,
        *,
        origin_radio: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BridgeDecision:
        annotated = self.annotate_ingress(packet, origin_radio=origin_radio, metadata=metadata)
        packet_id = annotated.get("packet_id")
        duplicate = self._is_duplicate(packet_id)
        if duplicate:
            annotated["bridged"] = False
            annotated["bridge_tx_targets"] = []
            return BridgeDecision(
                packet_id=packet_id,
                is_duplicate=True,
                metadata=annotated,
                target_endpoint_ids=[],
            )

        self._mark_seen(packet_id)
        targets = self.select_targets(origin_radio=annotated.get("origin_radio"))
        annotated["bridged"] = bool(targets)
        annotated["bridge_tx_targets"] = list(targets)
        return BridgeDecision(
            packet_id=packet_id,
            is_duplicate=False,
            metadata=annotated,
            target_endpoint_ids=targets,
        )

    def select_targets(self, *, origin_radio: Optional[str] = None) -> List[str]:
        targets: List[str] = []
        for endpoint in self.manager.healthy_endpoints():
            if origin_radio is not None and endpoint.endpoint_id == origin_radio:
                continue
            targets.append(endpoint.endpoint_id)
        return targets

    def should_deliver_to_router(self, decision: BridgeDecision) -> bool:
        return not decision.is_duplicate

    def record_duplicate_reception(self, packet: Any) -> Optional[str]:
        packet_id = self.packet_id(packet)
        self._mark_seen(packet_id)
        return packet_id

    def _is_duplicate(self, packet_id: Optional[str]) -> bool:
        if packet_id is None:
            return False
        self._prune_seen_packets()
        expiry = self._seen_packets.get(packet_id)
        return expiry is not None and expiry > time.time()

    def _mark_seen(self, packet_id: Optional[str]) -> None:
        if packet_id is None:
            return
        self._seen_packets[packet_id] = time.time() + self.dedupe_ttl

    def _prune_seen_packets(self) -> None:
        now = time.time()
        if len(self._seen_packets) <= 256:
            expired = [packet_id for packet_id, expiry in self._seen_packets.items() if expiry <= now]
            for packet_id in expired:
                self._seen_packets.pop(packet_id, None)
            return
        self._seen_packets = {
            packet_id: expiry
            for packet_id, expiry in self._seen_packets.items()
            if expiry > now
        }
