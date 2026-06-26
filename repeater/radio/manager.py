from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from repeater.radio.endpoints import RadioEndpoint, RadioEndpointState


def _default_builder(radio_config: Dict[str, Any]) -> Any:
    from repeater.config import get_radio_for_board

    return get_radio_for_board(radio_config)


@dataclass
class RadioManagerSummary:
    total: int
    enabled: int
    ready: int
    failed: int
    disabled: int


class RadioManager:
    def __init__(
        self,
        radios_config: Iterable[Dict[str, Any]],
        *,
        builder: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        self._builder = builder or _default_builder
        self._endpoints: List[RadioEndpoint] = []
        for index, radio_config in enumerate(radios_config):
            endpoint_name = str(radio_config.get("name") or f"radio{index + 1}")
            endpoint_id = str(radio_config.get("endpoint_id") or endpoint_name)
            self._endpoints.append(
                RadioEndpoint(
                    endpoint_id=endpoint_id,
                    name=endpoint_name,
                    enabled=bool(radio_config.get("enabled", True)),
                    radio_type=radio_config.get("radio_type"),
                    config=radio_config,
                    state=RadioEndpointState.DISABLED,
                )
            )

    @property
    def endpoints(self) -> List[RadioEndpoint]:
        return list(self._endpoints)

    def initialize_all(self) -> List[RadioEndpoint]:
        initialized: List[RadioEndpoint] = []
        for endpoint in self._endpoints:
            try:
                backend = endpoint.initialize(self._builder)
            except Exception:
                continue
            if backend is not None:
                initialized.append(endpoint)
        return initialized

    def healthy_endpoints(self) -> List[RadioEndpoint]:
        healthy = []
        for endpoint in self._endpoints:
            if endpoint.check_health():
                healthy.append(endpoint)
        return healthy

    def get_endpoint(self, endpoint_id: str) -> Optional[RadioEndpoint]:
        for endpoint in self._endpoints:
            if endpoint.endpoint_id == endpoint_id:
                return endpoint
        return None

    def shutdown_all(self) -> None:
        for endpoint in self._endpoints:
            endpoint.shutdown()

    def summary(self) -> RadioManagerSummary:
        total = len(self._endpoints)
        enabled = sum(1 for endpoint in self._endpoints if endpoint.enabled)
        ready = sum(1 for endpoint in self._endpoints if endpoint.state == RadioEndpointState.READY)
        failed = sum(1 for endpoint in self._endpoints if endpoint.state == RadioEndpointState.FAILED)
        disabled = sum(
            1 for endpoint in self._endpoints if endpoint.state == RadioEndpointState.DISABLED
        )
        return RadioManagerSummary(
            total=total,
            enabled=enabled,
            ready=ready,
            failed=failed,
            disabled=disabled,
        )

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        *,
        builder: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ) -> "RadioManager":
        radios = config.get("radios") or []
        return cls(radios, builder=builder)
