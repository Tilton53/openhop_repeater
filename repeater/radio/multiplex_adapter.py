from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, List, Optional

from repeater.radio.endpoints import RadioEndpoint
from repeater.radio.manager import RadioManager


class MultiplexRadioAdapter:
    """Dispatcher-facing single-radio-compatible facade over many radio endpoints."""

    def __init__(self, manager: RadioManager):
        self.manager = manager
        self._receive_callback: Optional[Callable[..., Any]] = None
        self._rx_callback: Optional[Callable[..., Any]] = None

    @property
    def endpoints(self) -> List[RadioEndpoint]:
        return self.manager.endpoints

    def healthy_endpoints(self) -> List[RadioEndpoint]:
        return self.manager.healthy_endpoints()

    def get_endpoint(self, endpoint_id: str) -> Optional[RadioEndpoint]:
        return self.manager.get_endpoint(endpoint_id)

    def set_receive_callback(self, callback: Callable[..., Any]) -> None:
        self._receive_callback = callback
        self._rx_callback = callback
        for endpoint in self.endpoints:
            backend = endpoint.backend
            if backend is None:
                continue
            setter = getattr(backend, "set_rx_callback", None)
            if not callable(setter):
                setter = getattr(backend, "set_receive_callback", None)
            if callable(setter):
                setter(self._build_receive_wrapper(endpoint))

    def set_rx_callback(self, callback: Callable[..., Any]) -> None:
        self.set_receive_callback(callback)

    def send(self, packet: Any, **kwargs) -> Dict[str, Any]:
        return self.send_all(packet, **kwargs)

    def send_all(self, packet: Any, **kwargs) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for endpoint in self.healthy_endpoints():
            results[endpoint.endpoint_id] = self.send_via(endpoint.endpoint_id, packet, **kwargs)
        return results

    def send_via(self, endpoint_id: str, packet: Any, **kwargs) -> Any:
        endpoint = self.get_endpoint(endpoint_id)
        if endpoint is None:
            raise KeyError(f"Unknown radio endpoint: {endpoint_id}")
        if endpoint.backend is None:
            raise RuntimeError(f"Radio endpoint is not initialized: {endpoint_id}")

        sender = getattr(endpoint.backend, "send", None)
        if sender is None:
            sender = getattr(endpoint.backend, "send_packet", None)
        if not callable(sender):
            raise AttributeError(f"Radio endpoint does not expose send/send_packet: {endpoint_id}")
        return sender(packet, **kwargs)

    def sleep(self) -> None:
        self.manager.shutdown_all()

    def check_radio_health(self) -> bool:
        return bool(self.healthy_endpoints())

    def get_last_rssi(self) -> Optional[int]:
        values = [endpoint.last_rssi for endpoint in self.healthy_endpoints() if endpoint.last_rssi is not None]
        if not values:
            return None
        return max(values)

    def get_last_snr(self) -> Optional[float]:
        values = [endpoint.last_snr for endpoint in self.healthy_endpoints() if endpoint.last_snr is not None]
        if not values:
            return None
        return max(values)

    def _build_receive_wrapper(self, endpoint: RadioEndpoint) -> Callable[..., Any]:
        def _wrapper(packet: Any, *args, **kwargs):
            metadata = dict(kwargs.pop("metadata", {}) or {})
            metadata.setdefault("origin_radio", endpoint.endpoint_id)
            metadata.setdefault("rx_radio", endpoint.endpoint_id)
            metadata.setdefault("radio_name", endpoint.name)
            kwargs["metadata"] = metadata
            if self._receive_callback is None:
                return None
            result = self._receive_callback(packet, *args, **kwargs)
            if inspect.isawaitable(result):
                return result
            return result

        return _wrapper
