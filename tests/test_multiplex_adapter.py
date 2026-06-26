from unittest.mock import MagicMock

import pytest

from repeater.radio.endpoints import RadioEndpoint, RadioEndpointState
from repeater.radio.manager import RadioManager
from repeater.radio.multiplex_adapter import MultiplexRadioAdapter


class _Backend:
    def __init__(self, *, healthy=True, rssi=-90, snr=7.5, noise_floor=-120):
        self._healthy = healthy
        self._rssi = rssi
        self._snr = snr
        self._noise_floor = noise_floor
        self.callback = None
        self.sent_packets = []

    def check_radio_health(self):
        return self._healthy

    def get_last_rssi(self):
        return self._rssi

    def get_last_snr(self):
        return self._snr

    def get_noise_floor(self):
        return self._noise_floor

    def set_receive_callback(self, callback):
        self.callback = callback

    def send(self, packet, **kwargs):
        self.sent_packets.append((packet, kwargs))
        return {"packet": packet, "kwargs": kwargs}


def _manager_with_backends():
    backends = {}

    def _builder(cfg):
        backend = _Backend(
            healthy=cfg["name"] != "degraded",
            rssi=cfg.get("rssi", -90),
            snr=cfg.get("snr", 7.5),
            noise_floor=cfg.get("noise_floor", -120),
        )
        backends[cfg["name"]] = backend
        return backend

    manager = RadioManager(
        [
            {"name": "alpha", "enabled": True, "radio_type": "sx1262", "rssi": -88, "snr": 3.5},
            {
                "name": "beta",
                "enabled": True,
                "radio_type": "pymc_tcp",
                "rssi": -70,
                "snr": 9.0,
                "noise_floor": -108,
            },
            {"name": "degraded", "enabled": True, "radio_type": "kiss"},
        ],
        builder=_builder,
    )
    manager.initialize_all()
    return manager, backends


def test_multiplex_adapter_wraps_callbacks_with_origin_metadata():
    manager, backends = _manager_with_backends()
    adapter = MultiplexRadioAdapter(manager)
    received = []

    def _callback(packet, *args, **kwargs):
        received.append((packet, args, kwargs))

    adapter.set_receive_callback(_callback)

    packet = object()
    backends["alpha"].callback(packet, 123, metadata={"custom": True})

    assert len(received) == 1
    delivered_packet, delivered_args, delivered_kwargs = received[0]
    assert delivered_packet is packet
    assert delivered_args == (123,)
    assert delivered_kwargs["metadata"] == {
        "custom": True,
        "origin_radio": "alpha",
        "rx_radio": "alpha",
        "radio_name": "alpha",
    }


def test_multiplex_adapter_set_rx_callback_aliases_set_receive_callback():
    manager, backends = _manager_with_backends()
    adapter = MultiplexRadioAdapter(manager)
    received = []

    def _callback(packet, *args, **kwargs):
        received.append((packet, args, kwargs))

    adapter.set_rx_callback(_callback)

    packet = object()
    backends["beta"].callback(packet, metadata={})

    assert adapter._rx_callback is _callback
    assert len(received) == 1
    assert received[0][2]["metadata"]["origin_radio"] == "beta"


@pytest.mark.asyncio
async def test_multiplex_adapter_send_all_uses_healthy_targets_only():
    manager, backends = _manager_with_backends()
    adapter = MultiplexRadioAdapter(manager)

    result = await adapter.send_all("payload", wait_for_ack=False)

    assert set(result) == {"alpha", "beta"}
    assert backends["alpha"].sent_packets == [("payload", {"wait_for_ack": False})]
    assert backends["beta"].sent_packets == [("payload", {"wait_for_ack": False})]
    assert backends["degraded"].sent_packets == []
    assert adapter.check_radio_health() is True
    assert adapter.get_last_rssi() == -70
    assert adapter.get_last_snr() == 9.0
    assert adapter.get_noise_floor() == -108


@pytest.mark.asyncio
async def test_multiplex_adapter_send_via_validates_endpoint_availability():
    manager, backends = _manager_with_backends()
    adapter = MultiplexRadioAdapter(manager)

    direct_result = await adapter.send_via("beta", "packet", priority="high")

    assert direct_result == {"packet": "packet", "kwargs": {"priority": "high"}}
    assert backends["beta"].sent_packets == [("packet", {"priority": "high"})]

    disabled_endpoint = RadioEndpoint(
        endpoint_id="cold",
        name="cold",
        radio_type="sx1262",
        config={"name": "cold", "enabled": True},
        enabled=True,
        state=RadioEndpointState.FAILED,
    )
    manager._endpoints.append(disabled_endpoint)

    with pytest.raises(KeyError):
        await adapter.send_via("missing", "packet")

    with pytest.raises(RuntimeError):
        await adapter.send_via("cold", "packet")
