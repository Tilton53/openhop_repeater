import sys
import types

import yaml
import pytest

_openhop_core = types.ModuleType("openhop_core")
_protocol = types.ModuleType("openhop_core.protocol")
_constants = types.ModuleType("openhop_core.protocol.constants")
_constants.PAYLOAD_TYPE_GRP_DATA = 1
_constants.PAYLOAD_TYPE_GRP_TXT = 2
_crypto = types.ModuleType("openhop_core.protocol.crypto")


class _DummyCryptoUtils:
    @staticmethod
    def _hmac_sha256(secret, ciphertext):
        return b"\x00" * 32

    @staticmethod
    def _aes_decrypt(key, ciphertext):
        return b""


_crypto.CryptoUtils = _DummyCryptoUtils
_protocol.constants = _constants
_protocol.crypto = _crypto
_openhop_core.protocol = _protocol
_hardware = types.ModuleType("openhop_core.hardware")
_sx1262_wrapper = types.ModuleType("openhop_core.hardware.sx1262_wrapper")
_sx1262_wrapper.SX1262Radio = None
_tcp_radio = types.ModuleType("openhop_core.hardware.tcp_radio")
_tcp_radio.TCPLoRaRadio = None
_usb_radio = types.ModuleType("openhop_core.hardware.usb_radio")
_usb_radio.USBLoRaRadio = None
_kiss_modem_wrapper = types.ModuleType("openhop_core.hardware.kiss_modem_wrapper")
_kiss_modem_wrapper.KissModemWrapper = None
_hardware.sx1262_wrapper = _sx1262_wrapper
_hardware.tcp_radio = _tcp_radio
_hardware.usb_radio = _usb_radio
_hardware.kiss_modem_wrapper = _kiss_modem_wrapper
_openhop_core.hardware = _hardware
sys.modules.setdefault("openhop_core", _openhop_core)
sys.modules.setdefault("openhop_core.protocol", _protocol)
sys.modules.setdefault("openhop_core.protocol.constants", _constants)
sys.modules.setdefault("openhop_core.protocol.crypto", _crypto)
sys.modules.setdefault("openhop_core.hardware", _hardware)
sys.modules.setdefault("openhop_core.hardware.sx1262_wrapper", _sx1262_wrapper)
sys.modules.setdefault("openhop_core.hardware.tcp_radio", _tcp_radio)
sys.modules.setdefault("openhop_core.hardware.usb_radio", _usb_radio)
sys.modules.setdefault("openhop_core.hardware.kiss_modem_wrapper", _kiss_modem_wrapper)

from repeater.config import get_radio_for_board, load_config
from repeater.radio.manager import RadioManager


class _DummyRadio:
    _initialized = True

    def begin(self):
        return True


def test_load_config_normalizes_legacy_single_radio(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "radio_type": "pymc_tcp",
                "radio": {"frequency": 915000000, "tx_power": 20},
                "pymc_tcp": {"host": "bridge.local", "port": 5055},
                "repeater": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repeater.config._load_or_create_identity_key",
        lambda path=None: b"0" * 32,
    )

    config = load_config(str(config_path))

    assert len(config["radios"]) == 1
    radio = config["radios"][0]
    assert radio["name"] == "radio1"
    assert radio["enabled"] is True
    assert radio["radio_type"] == "pymc_tcp"
    assert radio["pymc_tcp"]["host"] == "bridge.local"
    assert radio["radio"]["frequency"] == 915000000
    assert radio["radio"]["tx_power"] == 20
    assert radio["radio"]["bandwidth"] == 62500
    assert config["radio_type"] == "pymc_tcp"
    assert config["radio"]["frequency"] == 915000000


def test_load_config_preserves_explicit_radios_and_applies_defaults(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "radio_type": "sx1262",
                "radio": {"frequency": 869618000, "tx_power": 14},
                "radios": [
                    {
                        "name": "local",
                        "radio_type": "sx1262",
                        "sx1262": {
                            "bus_id": 0,
                            "cs_id": 0,
                            "cs_pin": 21,
                            "reset_pin": 18,
                            "busy_pin": 20,
                            "irq_pin": 16,
                            "txen_pin": -1,
                            "rxen_pin": -1,
                        },
                    },
                    {
                        "radio_type": "pymc_tcp",
                        "enabled": False,
                        "pymc_tcp": {"host": "modem.local"},
                        "radio": {"tx_power": 22, "preamble_length": 16},
                    },
                ],
                "repeater": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repeater.config._load_or_create_identity_key",
        lambda path=None: b"1" * 32,
    )

    config = load_config(str(config_path))

    assert [radio["name"] for radio in config["radios"]] == ["local", "radio2"]
    assert config["radios"][0]["enabled"] is True
    assert config["radios"][1]["enabled"] is False
    assert config["radios"][0]["radio"]["frequency"] == 869618000
    assert config["radios"][0]["radio"]["bandwidth"] == 62500
    assert config["radios"][1]["radio"]["frequency"] == 869618000
    assert config["radios"][1]["radio"]["tx_power"] == 22
    assert config["radios"][1]["radio"]["preamble_length"] == 16


def test_radio_manager_from_config_uses_normalized_radios(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "radios": [
                    {
                        "name": "local",
                        "radio_type": "sx1262",
                        "sx1262": {
                            "bus_id": 0,
                            "cs_id": 0,
                            "cs_pin": 21,
                            "reset_pin": 18,
                            "busy_pin": 20,
                            "irq_pin": 16,
                            "txen_pin": -1,
                            "rxen_pin": -1,
                        },
                    },
                    {
                        "radio_type": "pymc_tcp",
                        "pymc_tcp": {"host": "modem.local"},
                    },
                ],
                "repeater": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "repeater.config._load_or_create_identity_key",
        lambda path=None: b"2" * 32,
    )

    config = load_config(str(config_path))
    manager = RadioManager.from_config(config, builder=lambda cfg: _DummyRadio())
    initialized = manager.initialize_all()

    assert [endpoint.name for endpoint in manager.endpoints] == ["local", "radio2"]
    assert [endpoint.name for endpoint in initialized] == ["local", "radio2"]
    assert manager.summary().ready == 2


def test_get_radio_for_board_passes_en_pins(monkeypatch):
    captured_kwargs = {}

    class _DummySX1262Radio:
        @classmethod
        def get_instance(cls, **kwargs):
            captured_kwargs.update(kwargs)
            return _DummyRadio()

    monkeypatch.setattr(
        "openhop_core.hardware.sx1262_wrapper.SX1262Radio",
        _DummySX1262Radio,
    )

    board_config = {
        "radio_type": "sx1262",
        "sx1262": {
            "bus_id": 0,
            "cs_id": 0,
            "cs_pin": -1,
            "reset_pin": 18,
            "busy_pin": 5,
            "irq_pin": 6,
            "txen_pin": -1,
            "rxen_pin": -1,
            "en_pins": [26, 23],
        },
        "radio": {
            "frequency": 915000000,
            "tx_power": 22,
            "spreading_factor": 9,
            "bandwidth": 125000,
            "coding_rate": 5,
            "preamble_length": 17,
            "sync_word": 0x3444,
        },
    }

    get_radio_for_board(board_config)

    assert captured_kwargs["en_pins"] == [26, 23]
    assert "en_pin" not in captured_kwargs


def test_get_radio_for_board_null_radio_type_returns_null_radio():
    radio = get_radio_for_board({"radio_type": None})
    assert type(radio).__name__ == "NullRadio"


def test_get_radio_for_board_missing_radio_type_returns_null_radio():
    radio = get_radio_for_board({})
    assert type(radio).__name__ == "NullRadio"


def test_get_radio_for_board_uses_default_radio_values_for_per_radio_entry(monkeypatch):
    captured = {}

    class _DummyTCPLoRaRadio(_DummyRadio):
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "openhop_core.hardware.tcp_radio.TCPLoRaRadio",
        _DummyTCPLoRaRadio,
    )

    get_radio_for_board(
        {
            "name": "remote",
            "radio_type": "pymc_tcp",
            "pymc_tcp": {"host": "modem.local"},
        }
    )

    assert captured["frequency"] == 869618000
    assert captured["bandwidth"] == 62500
    assert captured["spreading_factor"] == 8
    assert captured["coding_rate"] == 8
    assert captured["tx_power"] == 14
    assert captured["preamble_length"] == 32


# ─── pymc_tcp / pymc_usb branches ────────────────────────────────────


def _pymc_radio_cfg():
    """Common radio params for the pymc_* tests."""
    return {
        "frequency": 869618000,
        "tx_power": 22,
        "spreading_factor": 8,
        "bandwidth": 62500,
        "coding_rate": 8,
        "preamble_length": 16,
        "sync_word": 0x12,
    }


def test_get_radio_for_board_pymc_tcp(monkeypatch):
    pytest.importorskip("openhop_core.hardware.tcp_radio")
    captured = {}

    class _DummyTCPLoRaRadio(_DummyRadio):
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "openhop_core.hardware.tcp_radio.TCPLoRaRadio",
        _DummyTCPLoRaRadio,
    )

    board_config = {
        "radio_type": "pymc_tcp",
        "pymc_tcp": {
            "host": "pymc-3e2834.local",
            "port": 5055,
            "token": "shared-secret",
            "connect_timeout": 7.5,
            "lbt_enabled": False,
            "lbt_max_attempts": 3,
        },
        "radio": _pymc_radio_cfg(),
    }

    get_radio_for_board(board_config)

    assert captured["host"] == "pymc-3e2834.local"
    assert captured["port"] == 5055
    assert captured["token"] == "shared-secret"
    assert captured["connect_timeout"] == 7.5
    assert captured["frequency"] == 869618000
    assert captured["sync_word"] == 0x12
    assert captured["lbt_enabled"] is False
    assert captured["lbt_max_attempts"] == 3


def test_get_radio_for_board_pymc_tcp_requires_host(monkeypatch):
    pytest.importorskip("openhop_core.hardware.tcp_radio")

    monkeypatch.setattr(
        "openhop_core.hardware.tcp_radio.TCPLoRaRadio",
        lambda **kwargs: _DummyRadio(),
    )

    board_config = {
        "radio_type": "pymc_tcp",
        "pymc_tcp": {"port": 5055},
        "radio": _pymc_radio_cfg(),
    }

    with pytest.raises(ValueError, match="Missing 'host'"):
        get_radio_for_board(board_config)


def test_get_radio_for_board_pymc_usb(monkeypatch):
    pytest.importorskip("openhop_core.hardware.usb_radio")
    captured = {}

    class _DummyUSBLoRaRadio(_DummyRadio):
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "openhop_core.hardware.usb_radio.USBLoRaRadio",
        _DummyUSBLoRaRadio,
    )

    board_config = {
        "radio_type": "pymc_usb",
        "pymc_usb": {
            "port": "/dev/ttyACM0",
            "baudrate": 921600,
        },
        "radio": _pymc_radio_cfg(),
    }

    get_radio_for_board(board_config)

    assert captured["port"] == "/dev/ttyACM0"
    assert captured["baudrate"] == 921600
    assert captured["frequency"] == 869618000
    assert captured["sync_word"] == 0x12
    # LBT defaults preserved when omitted from pymc_usb section.
    assert captured["lbt_enabled"] is True
    assert captured["lbt_max_attempts"] == 5


def test_get_radio_for_board_pymc_usb_requires_port(monkeypatch):
    pytest.importorskip("openhop_core.hardware.usb_radio")

    monkeypatch.setattr(
        "openhop_core.hardware.usb_radio.USBLoRaRadio",
        lambda **kwargs: _DummyRadio(),
    )

    board_config = {
        "radio_type": "pymc_usb",
        # Section present (baudrate set) but `port` deliberately omitted to
        # exercise the inner "Missing 'port'" guard rather than the outer
        # "Missing 'pymc_usb' section" one.
        "pymc_usb": {"baudrate": 921600},
        "radio": _pymc_radio_cfg(),
    }

    with pytest.raises(ValueError, match="Missing 'port'"):
        get_radio_for_board(board_config)


# ─── kiss branch: optional CSMA / key-up tuning forwarding ────────────


def _kiss_capture_radio_config(monkeypatch):
    """Patch KissModemWrapper to capture the radio_config it is built with."""
    pytest.importorskip("openhop_core.hardware.kiss_modem_wrapper")
    captured = {}

    class _DummyKissWrapper(_DummyRadio):
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "openhop_core.hardware.kiss_modem_wrapper.KissModemWrapper",
        _DummyKissWrapper,
    )
    return captured


def test_get_radio_for_board_kiss_forwards_csma_tuning(monkeypatch):
    captured = _kiss_capture_radio_config(monkeypatch)

    board_config = {
        "radio_type": "kiss",
        "kiss": {
            "port": "/dev/ttyACM0",
            "baud_rate": 115200,
            "kiss_persistence": 255,
            "kiss_slottime_ms": 20,
            "tx_delay_ms": 50,
            "kiss_full_duplex": True,
        },
        "radio": _pymc_radio_cfg(),
    }

    get_radio_for_board(board_config)

    rc = captured["kwargs"]["radio_config"]
    assert rc["kiss_persistence"] == 255
    assert rc["kiss_slottime_ms"] == 20
    assert rc["tx_delay_ms"] == 50
    assert rc["kiss_full_duplex"] is True


def test_get_radio_for_board_kiss_omits_unset_tuning(monkeypatch):
    captured = _kiss_capture_radio_config(monkeypatch)

    board_config = {
        "radio_type": "kiss",
        "kiss": {"port": "/dev/ttyACM0", "baud_rate": 115200},
        "radio": _pymc_radio_cfg(),
    }

    get_radio_for_board(board_config)

    rc = captured["kwargs"]["radio_config"]
    # Unset keys must not be forwarded, so the wrapper keeps its own defaults.
    for key in ("kiss_persistence", "kiss_slottime_ms", "tx_delay_ms", "kiss_full_duplex"):
        assert key not in rc
