from repeater.radio.endpoints import RadioEndpoint, RadioEndpointState
from repeater.radio.manager import RadioManager


class _Backend:
    def __init__(self, *, healthy=True, rssi=-90, snr=7.5):
        self._healthy = healthy
        self._rssi = rssi
        self._snr = snr
        self.sleep_calls = 0

    def check_radio_health(self):
        return self._healthy

    def get_last_rssi(self):
        return self._rssi

    def get_last_snr(self):
        return self._snr

    def sleep(self):
        self.sleep_calls += 1


def test_radio_endpoint_initialize_and_health_metrics():
    endpoint = RadioEndpoint(
        endpoint_id="local",
        name="local",
        radio_type="sx1262",
        config={"name": "local", "radio_type": "sx1262", "enabled": True},
        enabled=True,
    )

    backend = endpoint.initialize(lambda cfg: _Backend())

    assert isinstance(backend, _Backend)
    assert endpoint.state == RadioEndpointState.READY
    assert endpoint.last_rssi == -90
    assert endpoint.last_snr == 7.5
    assert endpoint.check_health() is True
    assert endpoint.counters.health_checks == 1


def test_radio_manager_initializes_enabled_radios_and_isolates_failures():
    built = []

    def _builder(cfg):
        built.append(cfg["name"])
        if cfg["name"] == "broken":
            raise RuntimeError("boom")
        return _Backend()

    manager = RadioManager(
        [
            {"name": "local", "enabled": True, "radio_type": "sx1262"},
            {"name": "broken", "enabled": True, "radio_type": "pymc_tcp"},
            {"name": "disabled", "enabled": False, "radio_type": "kiss"},
        ],
        builder=_builder,
    )

    initialized = manager.initialize_all()

    assert [endpoint.name for endpoint in initialized] == ["local"]
    assert built == ["local", "broken"]
    assert manager.get_endpoint("broken").state == RadioEndpointState.FAILED
    assert manager.get_endpoint("disabled").state == RadioEndpointState.DISABLED


def test_radio_manager_reports_healthy_endpoints_and_shutdown():
    backends = {}

    def _builder(cfg):
        backend = _Backend(healthy=cfg["name"] != "degraded")
        backends[cfg["name"]] = backend
        return backend

    manager = RadioManager(
        [
            {"name": "ready", "enabled": True, "radio_type": "sx1262"},
            {"name": "degraded", "enabled": True, "radio_type": "pymc_tcp"},
        ],
        builder=_builder,
    )

    manager.initialize_all()
    healthy = manager.healthy_endpoints()

    assert [endpoint.name for endpoint in healthy] == ["ready"]
    summary = manager.summary()
    assert summary.total == 2
    assert summary.enabled == 2
    assert summary.ready == 1
    assert summary.failed == 1

    manager.shutdown_all()

    assert backends["ready"].sleep_calls == 1
    assert backends["degraded"].sleep_calls == 1
    assert manager.get_endpoint("ready").state == RadioEndpointState.STOPPED
