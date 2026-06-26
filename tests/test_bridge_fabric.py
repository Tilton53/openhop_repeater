from repeater.radio.bridge_fabric import RadioBridgeFabric
from repeater.radio.manager import RadioManager


class _Backend:
    def __init__(self, *, healthy=True):
        self._healthy = healthy

    def check_radio_health(self):
        return self._healthy


class _Packet:
    def __init__(self, packet_hash: bytes):
        self._packet_hash = packet_hash

    def calculate_packet_hash(self):
        return self._packet_hash


def _manager():
    def _builder(cfg):
        return _Backend(healthy=cfg["name"] != "gamma")

    manager = RadioManager(
        [
            {"name": "alpha", "enabled": True, "radio_type": "sx1262"},
            {"name": "beta", "enabled": True, "radio_type": "pymc_tcp"},
            {"name": "gamma", "enabled": True, "radio_type": "kiss"},
            {"name": "disabled", "enabled": False, "radio_type": "kiss"},
        ],
        builder=_builder,
    )
    manager.initialize_all()
    return manager


def test_bridge_fabric_annotates_metadata_and_excludes_origin():
    fabric = RadioBridgeFabric(_manager())
    packet = _Packet(b"\xAA" * 8)

    decision = fabric.build_decision(packet, origin_radio="alpha", metadata={"rssi": -91})

    assert decision.is_duplicate is False
    assert decision.packet_id == (b"\xAA" * 8).hex().upper()
    assert decision.target_endpoint_ids == ["beta"]
    assert decision.metadata["origin_radio"] == "alpha"
    assert decision.metadata["rx_radio"] == "alpha"
    assert decision.metadata["bridged"] is True
    assert decision.metadata["bridge_tx_targets"] == ["beta"]
    assert decision.metadata["rssi"] == -91
    assert fabric.should_deliver_to_router(decision) is True


def test_bridge_fabric_suppresses_duplicates_after_first_ingress():
    fabric = RadioBridgeFabric(_manager())
    packet = _Packet(b"\xBB" * 8)

    first = fabric.build_decision(packet, origin_radio="alpha")
    duplicate = fabric.build_decision(packet, origin_radio="beta")

    assert first.is_duplicate is False
    assert first.target_endpoint_ids == ["beta"]
    assert duplicate.is_duplicate is True
    assert duplicate.target_endpoint_ids == []
    assert duplicate.metadata["bridged"] is False
    assert duplicate.metadata["bridge_tx_targets"] == []
    assert fabric.should_deliver_to_router(duplicate) is False


def test_bridge_fabric_local_origin_fans_out_to_all_healthy_radios():
    fabric = RadioBridgeFabric(_manager())
    packet = _Packet(b"\xCC" * 8)

    decision = fabric.build_decision(packet, origin_radio=None)

    assert decision.is_duplicate is False
    assert decision.target_endpoint_ids == ["alpha", "beta"]
    assert decision.metadata["bridge_tx_targets"] == ["alpha", "beta"]


def test_bridge_fabric_handles_packets_without_hashes_as_non_deduped():
    class _BadPacket:
        def calculate_packet_hash(self):
            raise RuntimeError("hash unavailable")

    fabric = RadioBridgeFabric(_manager())

    decision = fabric.build_decision(_BadPacket(), origin_radio="alpha")

    assert decision.packet_id is None
    assert decision.is_duplicate is False
    assert decision.target_endpoint_ids == ["beta"]
