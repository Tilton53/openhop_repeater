from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger("RadioEndpoint")


class RadioEndpointState(str, Enum):
    DISABLED = "disabled"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class RadioEndpointCounters:
    startup_attempts: int = 0
    startup_failures: int = 0
    health_checks: int = 0
    health_failures: int = 0


@dataclass
class RadioEndpoint:
    endpoint_id: str
    name: str
    radio_type: Optional[str]
    config: Dict[str, Any]
    enabled: bool = True
    backend: Any = None
    state: RadioEndpointState = RadioEndpointState.DISABLED
    counters: RadioEndpointCounters = field(default_factory=RadioEndpointCounters)
    last_error: Optional[str] = None
    last_rssi: Optional[int] = None
    last_snr: Optional[float] = None

    def initialize(self, builder) -> Any:
        self.counters.startup_attempts += 1
        if not self.enabled:
            self.state = RadioEndpointState.DISABLED
            self.backend = None
            self.last_error = None
            return None

        try:
            self.backend = builder(self.config)
        except Exception as exc:
            self.backend = None
            self.state = RadioEndpointState.FAILED
            self.counters.startup_failures += 1
            self.last_error = str(exc)
            raise

        self.state = RadioEndpointState.READY
        self.last_error = None
        self.refresh_signal_metrics()
        return self.backend

    def refresh_signal_metrics(self) -> None:
        if self.backend is None:
            self.last_rssi = None
            self.last_snr = None
            return

        self.last_rssi = self._read_metric("get_last_rssi")
        self.last_snr = self._read_metric("get_last_snr")

    def check_health(self) -> bool:
        self.counters.health_checks += 1
        if not self.enabled:
            self.state = RadioEndpointState.DISABLED
            return False

        if self.backend is None:
            self.state = RadioEndpointState.FAILED
            self.counters.health_failures += 1
            if self.last_error is None:
                self.last_error = "backend not initialized"
            return False

        try:
            checker = getattr(self.backend, "check_radio_health", None)
            healthy = True if checker is None else bool(checker())
        except Exception as exc:
            healthy = False
            self.last_error = str(exc)

        if healthy:
            self.state = RadioEndpointState.READY
            self.refresh_signal_metrics()
            return True

        self.state = RadioEndpointState.FAILED
        self.counters.health_failures += 1
        if self.last_error is None:
            self.last_error = "health check failed"
        return False

    def shutdown(self) -> None:
        if self.backend is not None:
            sleeper = getattr(self.backend, "sleep", None)
            if callable(sleeper):
                try:
                    sleeper()
                except Exception:
                    logger.exception("Failed to stop radio endpoint %s", self.name)
        self.state = RadioEndpointState.STOPPED if self.enabled else RadioEndpointState.DISABLED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_id": self.endpoint_id,
            "name": self.name,
            "enabled": self.enabled,
            "radio_type": self.radio_type,
            "state": self.state.value,
            "last_error": self.last_error,
            "last_rssi": self.last_rssi,
            "last_snr": self.last_snr,
            "counters": {
                "startup_attempts": self.counters.startup_attempts,
                "startup_failures": self.counters.startup_failures,
                "health_checks": self.counters.health_checks,
                "health_failures": self.counters.health_failures,
            },
        }

    def _read_metric(self, method_name: str):
        reader = getattr(self.backend, method_name, None)
        if callable(reader):
            try:
                value = reader()
            except Exception:
                return None
        else:
            value = getattr(self.backend, method_name.replace("get_", ""), None)
        return value
