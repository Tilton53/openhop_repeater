# Multi-Radio Internal Bridge Plan

## Goal

Add internal multi-radio support to [`openhop_repeater`](../README.md) so one repeater process can own multiple radios or modem transports simultaneously and bridge packets between them internally.

## Confirmed Requirements

- Single logical repeater identity shared across all radios.
- All enabled radios bridge to each other by default.
- Mixed transports are supported in the same repeater instance.
- Engine-originated packets transmit on every eligible radio by default.

## Current State Summary

The existing implementation is single-radio oriented:

- Config chooses one backend in [`radio_type`](../config.yaml.example).
- Radio construction happens in [`get_radio_for_board()`](../repeater/config.py:440).
- The daemon initializes one radio in [`RepeaterDaemon.initialize()`](../repeater/main.py:82).
- The dispatcher is bound once in [`Dispatcher(self.radio)`](../repeater/main.py:181).

Relevant MeshCore patterns:

- Bridge is treated as an internal adjunct transport in [`MyMesh`](../MeshCore/examples/simple_repeater/MyMesh.h:83).
- RX/TX bridge taps live around [`MyMesh::logRx()`](../MeshCore/examples/simple_repeater/MyMesh.cpp:475) and [`MyMesh::logTx()`](../MeshCore/examples/simple_repeater/MyMesh.cpp:501).
- Radio control abstraction is cleanly separated in [`KissModem`](../MeshCore/examples/kiss_modem/KissModem.h:100).

## Target Runtime Model

One repeater process will contain:

- one logical local identity
- one logical router and engine
- many radio endpoints
- one internal bridge fabric
- one dispatcher-facing multiplexed radio adapter

Behavior:

- Packet received on radio A is processed once.
- If allowed, it is bridged to all other enabled radios B, C, D.
- The same packet later heard on B is treated as a duplicate reception, not reprocessed and not re-bridged.
- Repeater-originated packets are sent on all eligible radios.

## Proposed Config Model

Add a top-level `radios` list while preserving backward compatibility.

### New shape

```yaml
radios:
  - name: lora_local
    enabled: true
    radio_type: sx1262
    radio:
      frequency: 869618000
      bandwidth: 62500
      spreading_factor: 8
      coding_rate: 8
      tx_power: 14
      preamble_length: 32
    sx1262:
      bus_id: 0
      cs_id: 0
      cs_pin: 21
      reset_pin: 18
      busy_pin: 20
      irq_pin: 16
      txen_pin: -1
      rxen_pin: -1

  - name: remote_modem
    enabled: true
    radio_type: pymc_tcp
    radio:
      frequency: 869618000
      bandwidth: 62500
      spreading_factor: 8
      coding_rate: 8
      tx_power: 22
      preamble_length: 16
    pymc_tcp:
      host: modem.local
      port: 5055
      token: ""
```

### Backward compatibility

Inside [`load_config()`](../repeater/config.py:196):

- If `radios` is absent, build `radios[0]` from legacy top-level keys.
- Continue accepting legacy keys during transition.
- Internally, treat `radios[]` as the source of truth.

## New Internal Components

### 1. `RadioEndpoint`

Purpose:
- represent one physical or modem-backed radio runtime

Fields:
- stable endpoint id
- name
- enabled flag
- radio type
- normalized config
- backend instance
- health state
- counters
- last RSSI and SNR

### 2. `RadioManager`

Purpose:
- build, store, start, monitor, and stop all endpoints

Responsibilities:
- initialize each enabled endpoint independently
- expose healthy endpoints
- isolate partial startup failures
- clean up all endpoints on shutdown

### 3. `MultiplexRadioAdapter`

Purpose:
- provide one dispatcher-compatible radio surface over multiple endpoints

Responsibilities:
- aggregate inbound packets from all radios
- attach `origin_radio` metadata
- expose radio methods expected by the dispatcher and helpers
- support explicit per-endpoint send when requested by the bridge fabric
- support all-radio send for repeater-originated traffic

### 4. `RadioBridgeFabric`

Purpose:
- host-side internal bridge layer between radio endpoints

Responsibilities:
- accept normalized packet ingress from any endpoint
- forward packet once into router and engine
- fan packet out to all other enabled radios
- prevent reflection back to source radio
- suppress re-bridging of duplicates

## Code Change Plan

### Phase 1: Configuration and builders

#### Update config loading
Files:
- [`load_config()`](../repeater/config.py:196)
- [`config.yaml.example`](../config.yaml.example)

Tasks:
- add `radios[]` normalization
- preserve legacy single-radio inputs
- ensure every radio entry has a normalized `name`, `enabled`, `radio_type`, and per-radio `radio` block

#### Refactor radio construction
Files:
- [`get_radio_for_board()`](../repeater/config.py:440)

Tasks:
- split into one-radio builder and many-radio builder
- keep support for:
  - [`sx1262`](../repeater/config.py:484)
  - [`kiss`](../repeater/config.py:562)
  - [`pymc_tcp`](../repeater/config.py:621)
  - [`pymc_usb`](../repeater/config.py:665)
- return endpoint-friendly runtime objects

### Phase 2: Multi-radio runtime

#### Add manager and endpoint wrappers
Likely new files:
- `repeater/radio/endpoints.py`
- `repeater/radio/manager.py`

Tasks:
- define endpoint wrapper dataclass or class
- define manager for lifecycle and health

#### Add dispatcher compatibility adapter
Likely new file:
- `repeater/radio/multiplex_adapter.py`

Tasks:
- receive from all endpoints
- expose dispatcher-compatible API
- route local outbound TX to all radios

### Phase 3: Bridge fabric and routing metadata

Likely new file:
- `repeater/radio/bridge_fabric.py`

Files to update:
- [`RepeaterDaemon.initialize()`](../repeater/main.py:82)
- [`PacketRouter`](../repeater/packet_router.py)

Tasks:
- attach `origin_radio` metadata at ingress
- process each packet once globally
- bridge to all radios except source
- record duplicate receptions without duplicate handling

### Phase 4: Daemon integration

Files:
- [`RepeaterDaemon`](../repeater/main.py:41)

Tasks:
- replace single `self.radio` assumption with multi-radio manager plus multiplex adapter
- keep a dispatcher-compatible radio object for existing engine paths
- update stats and health aggregation
- update shutdown in [`RepeaterDaemon._shutdown()`](../repeater/main.py:1256) to clean up every endpoint

### Phase 5: API and validation

Files:
- [`repeater/web/api_endpoints.py`](../repeater/web/api_endpoints.py)
- [`config.yaml.example`](../config.yaml.example)

Tasks:
- validate `radios[]`
- retain legacy validation for old configs
- expose per-radio status to the web API
- make setup tooling at least preserve multi-radio configs safely

### Phase 6: Tests

Files likely affected:
- `tests/test_radio_config.py`
- `tests/test_main_py_coverage.py`
- `tests/test_packet_router.py`
- new tests for radio manager and bridge fabric

Required tests:
- legacy single-radio config still works
- `radios[]` mixed transport config loads correctly
- packet received on A bridges to B and C only
- duplicate packet received on B after A is not reprocessed
- local advert transmits on all enabled radios
- one endpoint failure leaves others running
- shutdown cleans up every endpoint

## Behavior Rules

### Inbound packet from one radio

1. packet arrives from endpoint A
2. assign `origin_radio=A`
3. global dedup check
4. if first-seen:
   - deliver to existing router and helpers
   - if forwarding allowed, transmit to all enabled radios except A
5. if duplicate:
   - record duplicate reception for stats or UI
   - do not reprocess
   - do not re-bridge

### Repeater-originated packet

1. packet created by repeater engine or helper
2. no ingress source
3. transmit on all healthy enabled radios
4. apply per-radio transport and timing rules independently

## Recommended Data Model for Metadata

Packet metadata should carry fields like:

- `origin_radio`
- `rx_radio`
- `bridged`
- `bridge_tx_targets`
- `rx_timestamp`

This metadata should be visible to routing and stats paths but should not alter packet contents.

## Important Design Constraints

### Mixed transport support

The design must allow combinations like:
- local SPI plus [`pymc_tcp`](../repeater/config.py:621)
- local SPI plus [`pymc_usb`](../repeater/config.py:665)
- [`sx1262`](../repeater/config.py:484) plus [`kiss`](../repeater/config.py:562)

### RF compatibility

Different radios may have different RF settings.

First implementation recommendation:
- allow mixed RF configs
- emit warnings when enabled radios differ in frequency or critical LoRa parameters
- let the operator intentionally create bridges between different segments if desired

### Failure isolation

- one failed radio should not prevent the repeater from starting if at least one endpoint is healthy
- overall radio status should become degraded, not fatal, when partial failures occur

## Suggested File-Level Work Order

1. Update [`config.yaml.example`](../config.yaml.example) with `radios[]` examples and compatibility notes.
2. Update [`load_config()`](../repeater/config.py:196) to normalize legacy config into `radios[]`.
3. Refactor [`get_radio_for_board()`](../repeater/config.py:440) into reusable per-radio builders.
4. Add radio endpoint and manager modules.
5. Add multiplex adapter.
6. Integrate multi-radio startup into [`RepeaterDaemon.initialize()`](../repeater/main.py:82).
7. Add bridge fabric.
8. Update [`PacketRouter`](../repeater/packet_router.py) to understand origin metadata.
9. Update stats in [`RepeaterDaemon.get_stats()`](../repeater/main.py:1052).
10. Update shutdown in [`RepeaterDaemon._shutdown()`](../repeater/main.py:1256).
11. Update API validation and status surfaces in [`repeater/web/api_endpoints.py`](../repeater/web/api_endpoints.py).
12. Add and expand tests.

## Coding Agent Checklist

- [ ] Normalize config to `radios[]` in [`load_config()`](../repeater/config.py:196)
- [ ] Preserve legacy single-radio config support
- [ ] Refactor radio creation from [`get_radio_for_board()`](../repeater/config.py:440)
- [ ] Add `RadioEndpoint`
- [ ] Add `RadioManager`
- [ ] Add `MultiplexRadioAdapter`
- [ ] Add `RadioBridgeFabric`
- [ ] Integrate multi-radio runtime in [`RepeaterDaemon.initialize()`](../repeater/main.py:82)
- [ ] Update routing metadata in [`PacketRouter`](../repeater/packet_router.py)
- [ ] Fan local TX to all enabled radios
- [ ] Add per-radio stats to [`RepeaterDaemon.get_stats()`](../repeater/main.py:1052)
- [ ] Update shutdown logic in [`RepeaterDaemon._shutdown()`](../repeater/main.py:1256)
- [ ] Update validation and API exposure in [`repeater/web/api_endpoints.py`](../repeater/web/api_endpoints.py)
- [ ] Add test coverage for config, bridge fan-out, dedup, partial failure, and shutdown
- [ ] Document usage examples in [`README.md`](../README.md)

## Acceptance Criteria

Implementation is complete when:

- one repeater can start with multiple radios configured
- a packet heard on one radio is processed once and bridged to the others
- repeater-originated packets go out on all enabled radios
- mixed transport radios work in one process
- duplicate receptions across radios do not cause duplicate routing
- stats and API show per-radio health and counters
- legacy single-radio config still works without changes
