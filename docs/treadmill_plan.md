# Treadmill Acquisition Rewrite: Implementation Plan

## 1. Purpose and status

This document turns the requirements in `docs/treadmill_spec.md` into a test-first implementation plan for replacing the callback-based treadmill decoder. It is a plan, not an assertion that the system is production-ready.

> **Planning-only boundary for the current chat:** this chat is only refining this implementation plan. It must not write implementation code, write tests, change dependencies, run RED/GREEN implementation cycles, or make implementation commits. Implementation begins only in a later chat after the user approves the plan and the Phase 0 decisions are resolved.

This file is also the canonical implementation handoff record. The intended execution model is that a coordinating agent assigns the bounded work packages in this plan to **Terra Medium subagents** in later chats. The plan must contain enough context, contracts, tests, file ownership, dependencies, exit criteria, and recorded progress that a fresh coordinating agent or subagent can resume without relying on prior chat history.

Current plan state as of 2026-08-28:

| Item | State |
|---|---|
| Planning | In progress; expanded plan awaiting user review and answers to Section 18 |
| Implementation | **Not started** |
| Tests written/run for this rewrite | None |
| Implementation commits | None |
| Active implementation phase | None; Phase 0 is blocked on decisions/approval |
| Next action | Review this plan, answer Section 18, and explicitly approve it before a later implementation chat |

The implementation will use `debug/treadmill_decoder.py` as the calibration and behavior-facing reference, but it will replace that script's architecture. Production integration currently occurs through:

- `essential/treadmill_decoder.py`: the current `RPi.GPIO` A-rising decoder;
- `essential/Treadmill.py`: the session-facing wrapper and in-memory CSV recorder;
- `essential/behavbox.py`: construction, start, and stop integration;
- `session_info.py`: treadmill configuration;
- `main.py`: output paths and the main behavior loop.

The new system must not be declared ready for experiments until the synthetic, multiprocessing, physical rate-sweep, full-stack, and soak-test gates in this plan have passed.

### 1.1 How a fresh chat resumes this work

Before planning further or implementing anything, the coordinating agent must:

1. read the repository `AGENTS.md` in full;
2. read `docs/SoftwareDesign.md`, `docs/treadmill_spec.md`, and this entire plan, including the live ledger in Section 19;
3. inspect `git status` and preserve all unrelated/user changes;
4. inspect the files listed for the next work package and search their callers before editing;
5. confirm that the preceding work-package exit gate and required commits/evidence exist;
6. update Section 19 with the new chat/date, assigned work package, owner, starting commit, and exact intended scope;
7. propose the short implementation plan and tests required by `AGENTS.md`, and obtain user approval if the approved plan or requirements have materially changed;
8. execute only the recorded work package, using the test-first and commit protocol below.

Chat history is supplementary, not authoritative. If chat history conflicts with the current repository or this plan's recorded evidence, stop and resolve the discrepancy before implementation.

## 2. Findings that change the implementation

### 2.1 GPIO pin conflict is a blocking hardware/configuration issue

The current example assigns treadmill channels to BCM17 and BCM27. The live behavior stack already assigns:

- BCM17 to `cueLED1` in `essential/behavbox.py`;
- BCM27 to `lick2` in `essential/behavbox.py`.

The implementation must add whole-box GPIO allocation validation and the lab must choose two non-conflicting treadmill pins before hardware integration. The software must fail before claiming lines when conflicts exist. It must not attempt to share these pins or silently choose replacements.

### 2.2 The current wrapper is not suitable for the new architecture

`essential/Treadmill.py` currently stores every edge-derived row in an unbounded Python list and writes the entire CSV only at shutdown. It also receives one callback per decoded edge. This conflicts with fixed-rate, incremental, process-isolated logging and bounded memory requirements. The wrapper will remain as a compatibility facade, but its recording implementation will be replaced.

### 2.3 Current failure handling is unsafe

`BehavBox` currently catches treadmill initialization/start errors and continues, and treadmill shutdown catches all errors without reporting them. A required treadmill can therefore be absent or failed while the experiment proceeds. The rewrite must make required-treadmill startup fail closed, make health checks explicit during the behavior loop, and preserve shutdown errors in diagnostics.

### 2.4 The GPIO chip number cannot be hard-coded

Pi 4 commonly exposes the header GPIO controller as `pinctrl-bcm2711`; Pi 5 uses `pinctrl-rp1`, and its gpiochip number varies with kernel/device-tree versions. Resolution must be based on inspected chip/line metadata and Pi identity, with ambiguity treated as an error.

### 2.5 libgpiod buffer sizes have two meanings

The kernel event buffer and the userspace read batch are independent. The requested kernel buffer will default to 8192 events, subject to kernel adjustment. The Python `read_edge_events(max_events=...)` batch size will be separately configurable and initially capped at a modest value such as 256 or 1024. The effective behavior must be measured on both target Pi generations.

## 3. Decisions and approval gates

The following decisions are recommended so the plan is implementable. They must be confirmed before Phase 1 implementation begins.

1. **Production scope:** rewrite the production path under `essential/`, not only the debug script. Keep `debug/treadmill_decoder.py` unchanged as a historical/calibration reference until migration is complete.
2. **Public compatibility boundary:** keep imports of `essential.treadmill_decoder.TreadmillDecoder` and the `essential.Treadmill.Treadmill` class working where practical. Preserve `start()`, `snapshot()`, `zero()`, `stop()`, and `close()`. Replace ambiguous raw-count fields in new code with explicit transition and physical-unit fields; provide documented read-only legacy aliases only if a current caller requires them.
3. **Logging format:** use incrementally written CSV for the 200 Hz normal record plus JSON/JSONL sidecars for metadata, diagnostic events, and the final summary. This adds no dependency, remains readable after abnormal termination, and preserves compatibility with current lab workflows. Measure MB/hour during validation; change to a fixed-record binary format only if measured storage or CPU cost is unacceptable.
4. **Logger criticality:** default `continuous_logger_required = False`. Logger failure makes health `DEGRADED` and is loud, but does not invalidate encoder position. If configured `True`, logger failure makes health `FAILED`; it still does not set `integrity_valid = False` unless edge integrity was also lost.
5. **Calibration migration:** seed configuration with the explicitly unverified migration hypothesis `mm_per_encoder_cycle = 0.41095`, giving `mm_per_transition = 0.1027375`. Mark metadata as unverified and block production acceptance until physical calibration confirms or replaces it.
6. **Failure policy:** implement `warn`, `pause`, and `abort` as typed outcomes from the treadmill facade. The exact operator interaction for resuming a paused session is not defined by the spec and must be chosen before behavior-loop integration. No implementation may relabel `abort` as `pause`.
7. **Platform baseline:** select and record the supported Raspberry Pi OS, Python, kernel, and libgpiod/Python-binding versions before locking dependencies. The implementation will target the official libgpiod v2 API and fail its capability probe if required features are missing.
8. **Pin assignment:** select two BCM header pins not used elsewhere in `BehavBox` or the attached hardware. The pin map must be reviewed against the actual breakout board before Pi tests.

## 4. Proposed architecture

```text
Encoder A/B
    |
    v
libgpiod v2 backend (both edges, kernel monotonic timestamps, sequence numbers)
    |
    v
Acquisition process (only canonical-state writer)
    |-- edge adaptation and batch draining
    |-- pure x4 quadrature decoder
    |-- sequence/state-integrity checks
    |-- heartbeat and processing-lag statistics
    |-- bounded raw-event ring buffer
    |
    +--> nonblocking double-slot shared-state publisher
    |       |--> behavior facade: snapshot/health/zero
    |       `--> fixed-rate logger process
    |
    `--> bounded control/status channels
            |--> zero/stop/status commands and acknowledgements
            `--> logger status observed without blocking edge draining
```

Responsibilities stay separate:

- The GPIO backend resolves and requests lines and converts binding objects to generic events.
- The pure decoder owns quadrature, units, speed, zero offsets, and integrity counters; it has no GPIO, multiprocessing, logging, or wall-clock dependency.
- The acquisition worker owns the backend and decoder, drains edges before control work, publishes state, and maintains its heartbeat.
- The shared-state publisher provides coherent snapshots without allowing a reader-held lock to block acquisition.
- The logger samples the latest state on monotonic deadlines; it never receives every GPIO event.
- The public facade owns process lifecycle, startup handshake, reader-side stale-heartbeat detection, failure-policy signaling, and compatibility properties.
- The session wrapper maps session configuration/output paths to the facade; it does not buffer edge events.

## 5. Module and file layout

Create a small internal package rather than putting all responsibilities in one file. The first draft proposed separate catch-all `models.py` and `gpio_resolution.py` modules. After applying `docs/SoftwareDesign.md`, this plan instead keeps data beside the functions that interpret it, avoids a generic “models” dumping ground, and keeps GPIO resolution with the only production component that uses it.

```text
essential/
    treadmill_decoder.py                # stable public facade/re-exports
    Treadmill.py                        # session integration facade
    treadmill_acquisition/
        __init__.py
        config.py                       # validated immutable configuration
        quadrature.py                   # edge/decoder data plus deterministic functions
        state.py                        # public state, health, shared-layout conversions
        shared_state.py                 # nonblocking coherent publication
        gpio_backend.py                 # EdgeSource Protocol, resolver, libgpiod adapter
        acquisition.py                  # worker loop, handshake, controls, heartbeat
        continuous_logger.py            # monotonic 200 Hz sampler and incremental files
        diagnostics.py                  # counters, histogram, ring buffer, summaries

debug/
    treadmill_hardware_validate.py      # calibration/sign/rate/integrity utility
    treadmill_stress.py                 # synthetic/process/load stress utility

tests/
    treadmill/                          # focused unit/integration test package

docs/
    treadmill_setup.md                  # install, wiring, calibration, operation
    treadmill_validation.md             # rate sweep, soak test, acceptance records
```

Do not use the existing `essential/treadmill/` Arduino-sketch directory as the Python package; mixing firmware snapshots and runtime Python would be confusing. Do not modify the `.ino` files.

Do not create all files up front. Each module is added only when its work package begins and its tests demonstrate a current need. If implementation shows that two proposed modules are too small or inseparable, the coordinator must record and approve the simplification before changing the layout.

### 5.1 Module contracts and limitations

| Module | Purpose and inputs | Outputs/public boundary | Limitations/non-goals |
|---|---|---|---|
| `config.py` | Convert the treadmill portion of session configuration into an immutable, validated `TreadmillConfig`; accepts plain Python values | Config dataclass and closely related configuration enums/validation functions | Does not inspect GPIO devices, create processes, or write files |
| `quadrature.py` | Apply ordered `EdgeEvent` values and zero commands to an explicitly passed mutable `DecoderState` using calibration/sign scalars | `EdgeEvent`, private/internal decoder-state dataclass, deterministic module-level transition/speed/zero functions | No GPIO imports, clocks, IPC, logging, or public session logic; mutation is limited to the state argument and documented for hot-path efficiency |
| `state.py` | Define behavior-facing state/health and convert between explicit-width shared fields and immutable snapshots | `TreadmillState`, health/direction enums, fixed shared schema conversion functions | Does not own shared memory/locks or calculate quadrature transitions |
| `shared_state.py` | Publish/read coherent `state.py` fields through two nonblocking process-safe slots | Narrow publisher and reader objects used by acquisition, facade, and logger | No decoder, GPIO, health-policy, or file behavior |
| `gpio_backend.py` | Resolve BCM pins, validate/request libgpiod lines, synchronize initial state, and adapt batches to `EdgeEvent` | Narrow `EdgeSource` Protocol, production `GpiodEdgeSource`, pure resolver helpers | Only module importing `gpiod`; no decoding, multiprocessing ownership, or disk writes |
| `acquisition.py` | Run the worker around injected edge source, decoder state/functions, publisher, and bounded control/status endpoints | Top-level spawn-safe worker entry function and structured command/status dataclasses local to this boundary | Does not construct the behavior facade or logger and never performs disk I/O |
| `continuous_logger.py` | Schedule fixed-rate snapshot reads and incrementally write the defined recording artifacts | Top-level spawn-safe logger entry function plus focused scheduler/writer helpers | No edge stream, quadrature decoding, or behavior callbacks |
| `diagnostics.py` | Maintain bounded diagnostic aggregates/ring records and serialize diagnostic/summary structures | Focused dataclasses/functions consumed by decoder, worker, and logger | No process orchestration; does not become a general application logging framework |
| `essential/treadmill_decoder.py` | Composition/public API boundary: validate supplied config, assemble concrete defaults, own lifecycle, and expose simple behavior-facing operations | `TreadmillDecoder`, public state/config/errors re-exported intentionally | The only place allowed to know the complete runtime composition; no quadrature or libgpiod implementation details |
| `essential/Treadmill.py` | Translate existing session configuration/output basename to the public decoder facade | Backward-compatible session equipment interface where approved | No edge callbacks, event list, GPIO details, or duplicate health logic |

### 5.2 Design rules from `SoftwareDesign.md`

- Prefer module-level, deterministic functions for quadrature transitions, calibration, zeroing, deadline calculation, and serialization. Use classes only for cohesive stateful resources such as an acquired GPIO request, shared-state slots, or the public lifecycle facade.
- Use dataclasses for configuration and data records. Do not combine public data representation with unrelated orchestration behavior.
- Use composition, not inheritance. No mixins or class hierarchy are planned.
- Define a `Protocol` only where more than one real/test implementation is required. Initially this applies to the edge source; a narrower additional Protocol may be added only when a consumer demonstrably needs substitution. Do not create a broad `interfaces.py` module or one Protocol per class.
- Keep each Protocol beside its consumer or cohesive domain module. Production adapters and synthetic fakes must satisfy the same narrow contract without subclassing.
- Separate creation from use at the system boundary: `essential/treadmill_decoder.py` is the composition root that selects concrete production dependencies. Lower-level worker/logger functions receive only the dependencies/endpoints they use. Tests construct lower-level pieces directly with explicit fakes.
- Pass narrow values or dataclasses rather than the full `session_info` dictionary below `essential/Treadmill.py`. Helpers should not reach through facade internals or depend on concrete implementations.
- Avoid global mutable state, lambdas, convenience nested functions, currying, and control flags that make lower-level functions perform unrelated behaviors. Stable schema/version constants are allowed and documented.
- Type all function/method inputs and outputs and non-obvious class attributes. Avoid noisy annotations for obvious locals.
- Comments explain rationale, empirical constants, concurrency invariants, or non-obvious edge cases; names and small functions should explain routine mechanics.
- Every function/method and public dataclass documents input types, shapes where applicable, axis/order conventions, units, returns, exceptions, mutation/side effects, and lifecycle constraints.
- Optimize only the measured hot path. The explicit in-place decoder-state update is permitted to avoid per-edge allocations, but must remain deterministic from its provided state/event/config inputs and independently testable.

## 6. Core data contracts

### 6.1 Configuration

`TreadmillConfig` will be an immutable dataclass constructed from a plain mapping containing only the extracted treadmill settings. `essential/Treadmill.py` owns extraction from `session_info`; no internal acquisition module receives the full session dictionary. Fields and initial defaults:

| Field | Type/unit | Initial default or rule |
|---|---|---|
| `a_bcm_pin`, `b_bcm_pin` | `int`, BCM numbering | required, distinct, valid header GPIOs |
| `gpio_bias` | enum | `PULL_UP` |
| `debounce_period_us` | `int`, microseconds | `0`; never silently enabled |
| `mm_per_encoder_cycle` | positive `float`, mm/cycle | migration candidate `0.41095`, pending verification |
| `locomotion_sign` | `Literal[-1, 1]` | required before production use |
| `speed_timeout_s` | positive `float`, seconds | `0.050` |
| `kernel_event_buffer_size` | positive `int`, events | `8192` requested |
| `read_batch_size` | positive `int`, events | initial `256`; tune only from measurements |
| `continuous_log_enabled` | `bool` | `True` |
| `continuous_log_rate_hz` | positive `float`, Hz | `200.0` |
| `continuous_logger_required` | `bool` | recommended `False` |
| `treadmill_required` | `bool` | required for behavior-dependent use; passive logging may set `False` |
| `raw_edge_logging_enabled` | `bool` | `False` |
| `diagnostic_ring_buffer_size` | positive `int`, events | `8192` |
| `heartbeat_interval_s` | positive `float`, seconds | choose from measured scheduler behavior |
| `heartbeat_failure_timeout_s` | positive `float`, seconds | greater than heartbeat interval with explicit margin |
| `processing_lag_warning_ns` | positive `int`, ns | derive from buffer/rate validation |
| `startup_timeout_s` | positive `float`, seconds | explicit, bounded |
| `failure_policy` | `WARN`, `PAUSE`, `ABORT` | spec recommendation `PAUSE`, pending pause-semantics decision |
| `expected_max_transition_rate_hz` | optional positive `float`, Hz | required before production acceptance |

Validation will reject invalid values, pin conflicts, impossible heartbeat relationships, non-writable output destinations, and configurations whose buffer headroom is below a documented threshold once maximum event rate is known.

### 6.2 Generic edge event

Use a small frozen/slotted `EdgeEvent` with:

- `timestamp_ns: int` — kernel monotonic timestamp;
- `channel: EncoderChannel` — A or B, never an arbitrary integer;
- `edge_type: EdgeType` — rising or falling;
- `global_sequence_number: int`;
- `line_sequence_number: int`.

The pure decoder accepts an initial two-bit AB state and ordered `EdgeEvent` values. Synthetic and production sources use exactly this contract.

### 6.3 Public state

Use a typed `TreadmillState` containing at least:

- physical values: `position_mm`, `distance_travelled_mm`, `speed_mm_s`, `last_edge_speed_mm_s`;
- directions: `encoder_direction`, `locomotion_direction`, each `-1`, `0`, or `+1`;
- raw values: lifetime `raw_transition_position`, zero-relative `transition_position`, `equivalent_encoder_cycles`;
- monotonic timestamps in integer nanoseconds: last GPIO event, last valid position-changing edge, last motion, last state update, heartbeat;
- counters: edge events, valid/positive/negative transitions, reversals, sequence gaps, estimated missing events, state inconsistencies;
- lag aggregates: latest, sum/count, and maximum processing lag;
- health: enum state, `integrity_valid`, failure code/message identifier;
- `state_version`/publication generation.

`time_since_last_motion_s` and timeout-adjusted `speed_mm_s` are calculated from a caller-supplied/current monotonic timestamp when the snapshot is materialized. A dead acquisition heartbeat overrides effective reader-side health to `FAILED`; it must never appear as stationary/zero speed without failure status.

### 6.4 Diagnostics and summaries

Separate structures will represent:

- lifetime decoder diagnostics, which `zero()` cannot erase;
- logger timing/error diagnostics;
- startup/platform/GPIO metadata;
- end-of-session summary;
- diagnostic events with monotonic timestamp, category, severity, and structured context.

## 7. Pure decoder design

### 7.1 Quadrature transition table

Represent AB as integers `0b00` through `0b11`. Use an explicit 16-entry `(previous_state, new_state) -> {-1, 0, +1, invalid}` table. Confirm the specified positive sequence:

```text
00 -> 01 -> 11 -> 10 -> 00
```

and its negative reverse. Apply the event's declared edge to the remembered A/B bit; do not read current GPIO levels during normal decoding.

A valid single-bit state change updates signed and absolute lifetime transition totals. A duplicate edge inconsistent with the remembered bit, a two-bit jump, malformed channel, or timestamp/order anomaly increments its specific counter and follows an explicitly tested integrity policy. No missing transition is synthesized.

### 7.2 Position and zeroing

Keep integer lifetime state:

- `raw_transition_position` — signed net transitions since acquisition start;
- `absolute_transition_total` — sum of absolute valid deltas;
- `zero_transition_offset` and `zero_absolute_offset` — captured when a zero command is applied.

Calculate, never accumulate, floating-point physical values:

```text
mm_per_transition = mm_per_encoder_cycle / 4
position_mm = (raw_transition_position - zero_transition_offset)
              * mm_per_transition * locomotion_sign
distance_travelled_mm = (absolute_transition_total - zero_absolute_offset)
                        * mm_per_transition
```

Zero is executed in the acquisition process between drained event batches, publishes a new coherent state, and returns an acknowledgement containing the applied state version and timestamp. It does not reset lifetime diagnostics or restore invalid integrity.

### 7.3 Speed

For consecutive valid position-changing transitions, compute `dt_ns` only from kernel timestamps. If `dt_ns <= 0`, record a timing anomaly, latch failure according to the tested integrity matrix, and do not calculate a replacement speed.

`last_edge_speed_mm_s` is signed using transition delta, calibration, and `locomotion_sign`. `speed_mm_s` returns that value only while the last motion age is within `speed_timeout_s`; otherwise it returns zero while retaining the raw last-edge estimate. The first valid transition has no speed estimate. No smoothing or behavioral threshold is added.

### 7.4 Sequence integrity

Track expected global and per-line sequence numbers independently. On a forward jump, increment gap counts and estimated missing events, set `integrity_valid = False`, and latch `FAILED`. Regression/out-of-order values are separate anomalies. The decoder may resynchronize A/B state for diagnostic continuation, but the implementation and tests must document exactly which event becomes the new baseline; it must not repair position.

The detailed failure matrix—what increments, whether the current event changes position, whether AB state is resynchronized, and whether health/integrity latch—will be written as tests before decoder code. This avoids inventing behavior ad hoc during implementation.

## 8. GPIO backend and startup synchronization

### 8.1 Capability validation

At startup, import the official libgpiod v2 Python binding and verify actual support for:

- requesting both A/B lines together as inputs;
- both-edge detection;
- pull-up bias and explicit zero debounce;
- monotonic event clock;
- `wait_edge_events()` and batched `read_edge_events()`;
- line offset, edge type, timestamp ns, global sequence, and line sequence on each event;
- requested kernel event-buffer sizing.

If any capability is absent, raise an actionable startup exception. There is no `RPi.GPIO` fallback.

The narrow `EdgeSource` Protocol is the only planned behavioral abstraction around GPIO. Its conceptual contract is:

```text
open() -> None
    Resolve and claim resources; safe to close after partial failure.

synchronize(deadline_monotonic_ns: int) -> SynchronizedInputState
    Return coherent raw A/B levels, accepted sequence baselines, and mapping metadata;
    fail if a clean state is not established before the deadline.

wait_for_events(timeout_s: float) -> bool
    Wait at most timeout_s monotonic seconds; return whether events are pending.

read_events(max_events: int) -> list[EdgeEvent]
    Return 0..max_events events in backend/kernel order without decoding them.

close() -> None
    Idempotently release only owned resources.
```

`SynchronizedInputState` is a focused dataclass in `gpio_backend.py`, because it describes an edge-source operation rather than public treadmill state. The acquisition worker receives a top-level, spawn-pickleable edge-source creator and constructs the concrete source inside the child process; it never receives an already-open libgpiod object from the parent. Tests inject a top-level fake creator without subclassing.

### 8.2 BCM-to-chip resolution

Enumerate `/dev/gpiochip*` through libgpiod, inspect chip name/label/line count and line information, read Pi model/OS/kernel information, and select only a chip demonstrably representing the user-facing header controller. Expected labels such as `pinctrl-bcm2711` and `pinctrl-rp1` are evidence, not a blind exclusive list.

Require both configured BCM offsets to exist on the same selected header controller and be unclaimed/appropriate. Log every candidate and the reason it was accepted or rejected. Fail on zero or multiple plausible controllers. Provide a separately testable resolver fed synthetic chip inventories so Pi 4, old Pi 5 numbering, new Pi 5 numbering, ambiguity, missing pins, and claimed lines can be tested without hardware.

### 8.3 Race-safe initial synchronization

Use a bounded quiet-period/retry procedure:

1. Request both lines together with edge detection active.
2. Drain any already queued events.
3. Read A/B values together.
4. Wait a short configurable synchronization interval.
5. If an event arrives, drain it and retry from the value read, without applying an event twice.
6. Enter `READY` only after one quiet interval with no queued event between the final drain and accepted line-state sample.
7. Fail after a bounded number/time of retries with an actionable “treadmill moving during synchronization” error.

The exact ordering must be validated against the installed binding's request/read semantics on the target Pi. A deterministic fake backend will inject an event at every boundary in tests to prove no duplicate application or silent loss.

Events observed during a rejected synchronization attempt are not counted as session displacement. They are recorded as startup activity, drained, and used to advance sequence baselines before another simultaneous A/B value is sampled. Acquisition counters and position begin only at the accepted synchronized state. An edge queued after the accepted state read remains available and is decoded exactly once from that state.

### 8.4 Acquisition hot loop

The loop order will be:

1. wait for edges with a timeout no longer than the heartbeat deadline;
2. drain all available batches in kernel order;
3. adapt and decode events with no printing, disk I/O, or behavior callbacks;
4. publish state nonblockingly after a batch (not necessarily allocate/publish per edge);
5. update heartbeat on deadline even while stationary;
6. poll a bounded number of control/logger-status messages only after available edges are drained;
7. repeat immediately if more edges are pending.

Processing lag is `processing_monotonic_ns - event.timestamp_ns`. The worker's production composition supplies `time.monotonic_ns`; lower-level functions receive the sampled integer explicitly, and tests supply deterministic values rather than patching module globals. Maintain count, sum, maximum, latest, and a fixed-bin histogram in the hot path; derive percentiles from the histogram at summary time. The raw diagnostic ring is a bounded `deque(maxlen=...)` of compact records.

## 9. Nonblocking coherent shared state

Implement two fixed-layout shared-state slots, each with its own process-safe lock and publication generation.

- The acquisition writer tries to acquire a slot lock with `blocking=False`; it never waits for a reader.
- It writes a complete snapshot and generation while holding that slot's lock, releases it, then prefers the other slot on the next publication.
- Readers briefly lock and copy each available slot, release immediately, and return the coherent snapshot with the highest valid generation.
- If a reader is descheduled while holding one slot, the writer can use the other. If both slots are temporarily held, the writer skips that publication and continues consuming edges; it retries on the next batch/heartbeat and increments a publication-skip diagnostic.
- Readers have a bounded snapshot timeout and return the latest already copied state or raise a typed availability error; they never report a torn state as valid.

This design avoids relying on undocumented lock-free atomic/memory-order behavior in Python shared memory on ARM. It trades the possibility of a briefly stale published snapshot for preservation of acquisition correctness. The internal decoder state in the acquisition process remains canonical.

The fixed slot schema will use explicit-width `ctypes`/`multiprocessing` numeric fields and integer enum codes. Conversion to the ergonomic frozen public dataclass occurs in reader processes, outside the hot path.

## 10. Processes, controls, and lifecycle

### 10.1 Process ownership

The public `TreadmillDecoder` facade owns:

- one acquisition process;
- zero or one logger process;
- shared-state slots and auxiliary heartbeat/status fields;
- bounded command and acknowledgement channels;
- startup and shutdown events.

Select and document the multiprocessing start method explicitly after testing on Raspberry Pi OS. Prefer `spawn` for isolation from inherited GPIO/file/thread state unless measured startup or import constraints require another documented choice.

### 10.2 Startup

`start()` is idempotent only after a completed start; concurrent/reentrant starts are rejected. It will:

1. validate config and output paths before spawning;
2. create bounded IPC/shared structures;
3. start logger if enabled, then acquisition;
4. wait for structured startup messages covering capability check, GPIO resolution, line claim, synchronization, initial publication, and heartbeat;
5. return only when effective health is `READY` (or allowed `DEGRADED` for a non-required logger);
6. on timeout/error, request stop, terminate only as a last bounded cleanup step, join children, release resources, and raise the original actionable error.

No experiment starts after a treadmill-required startup failure.

### 10.3 Commands

Use bounded queues with nonblocking acquisition-side polling and nonblocking acknowledgements. Commands contain an ID and type (`ZERO`, `STOP`, `STATUS`). `zero()` waits with a caller-side timeout for the matching acknowledgement. Queue saturation is an explicit error, not a reason for acquisition to block.

### 10.4 Heartbeat and health

The acquisition worker publishes a heartbeat independently of motion. `snapshot()` and `require_healthy()` compare its age with the configured timeout. A stale heartbeat or dead child process produces effective `FAILED` even if the last canonical shared state said `READY`.

Health transitions are explicit and tested:

- `STARTING -> READY` after the full handshake;
- `READY -> DEGRADED` for lag warnings or a non-required logger failure;
- any active state `-> FAILED` for integrity loss, stale heartbeat, worker death, or unrecoverable backend error;
- active state `-> STOPPED` only after requested, completed shutdown.

`integrity_valid` is independent and latched until an explicit acquisition restart. Logger-only failure does not invalidate edge integrity.

### 10.5 Shutdown

`stop()` requests orderly cessation and waits within a timeout. Acquisition drains already available events, publishes final state/diagnostics, releases GPIO, and exits. Logger samples/finalizes after acquisition's final publication, flushes and closes files, and reports completion. `close()` is idempotent and joins processes; forced termination is a last resort and is written to the diagnostic summary. Shutdown errors remain visible.

## 11. Continuous and diagnostic logging

Use the existing `treadmill_filename` as a basename:

```text
<basename>.csv                       fixed-rate numeric state
<basename>_metadata.json             configuration/platform/timebase metadata
<basename>_diagnostics.jsonl         event-driven diagnostic records
<basename>_summary.json              final integrity/resource summary
<basename>_raw_failure_<stamp>.csv   ring-buffer dump on integrity failure
<basename>_raw_edges.csv             optional full raw-edge debug mode only
```

The 200 Hz CSV minimum columns will be:

```text
sample_monotonic_ns, position_mm, distance_travelled_mm,
speed_mm_s, last_edge_speed_mm_s, last_edge_monotonic_ns,
locomotion_direction, raw_transition_position,
health_code, integrity_valid, state_version
```

Write a header immediately, buffer a bounded number of rows, flush chunks incrementally, and periodically flush the Python buffer. Decide whether periodic `fsync` is worth its I/O cost from measurements; always flush and `fsync` during normal finalization. Never hold the full session in RAM.

The logger uses `next_deadline_ns += period_ns`. Deadline advancement/missed-period calculation is a deterministic module-level function receiving `now_ns`, `next_deadline_ns`, and `period_ns`. The process boundary supplies the production clock/wait operations; unit tests pass deterministic clock values without hidden global state. When late, the logger records the actual sample time, increments late/missed counts based on crossed deadlines, advances directly to the next future deadline, and emits one real sample—never duplicate catch-up rows.

The logger runs as a separate process and will request a modest lower scheduling priority using ordinary unprivileged OS facilities where supported. Whether that request succeeded is metadata, not a hidden assumption; priority setup failure must not prevent baseline operation.

At start and end, metadata records paired monotonic and UTC/realtime timestamps. Add periodic timebase anchors only if alignment tests show start/end anchors are insufficient. JSONL diagnostics record startup, resolved mapping, health transitions, zero acknowledgements, gaps/inconsistencies, logger/acquisition errors, and shutdown. Raw ring-buffer dumping occurs outside the acquisition hot path using a bounded handoff or after failure processing has stopped.

## 12. Behavior-stack integration and migration

### 12.1 `session_info.py`

- Expand `treadmill_setup` to the validated config fields.
- Add calibration-verification metadata rather than presenting `0.41095` as universally valid.
- Validate treadmill pins against a centralized map of all GPIO allocations for the selected rig configuration.
- Validate output/logging/failure-policy values before `BehavBox` construction.
- Keep session JSON serialization compatible with enums by storing plain strings/numbers in session configuration.

### 12.2 `essential/Treadmill.py`

- Convert to a thin session facade around `TreadmillDecoder(config, output_basename=...)`.
- Remove per-edge callbacks, the in-memory `treadmill_log`, `record_event()`, and end-only flush from production behavior.
- Expose `snapshot()`, `zero()`, `require_healthy()`, lifecycle methods, and temporary documented properties needed by existing callers.
- If legacy properties `counts`, `distance_mm`, `speed_mms`, or `direction` are retained, calculate them from the newest snapshot and issue clear migration documentation; do not imply x4 transitions equal old x1 counts.

### 12.3 `essential/behavbox.py` and `main.py`

- If treadmill is enabled/required, let initialization and startup errors abort startup rather than swallowing them.
- Start treadmill acquisition before `presenter.start_session()` and ensure it is stopped in all cleanup paths before file transfer.
- Add a lightweight health-policy check to each main-loop iteration, independent of task code.
- Implement the approved `warn`/`pause`/`abort` behavior without placing task thresholds in the acquisition layer.
- Make cleanup report treadmill failures while still attempting cleanup of cameras, stimuli, and other devices.
- Ensure treadmill metadata/summary files are included in the existing session-directory transfer.

### 12.4 Migration verification

On confirmed unchanged hardware, compare old x1 and new x4 acquisition during controlled motion using physical distance, not raw count equality. Verify that one old A-rising count corresponds to four valid x4 transitions and that both produce the same position within calibration tolerance. Determine `locomotion_sign` by moving in animal-forward direction and save it per rig.

## 13. Dependencies and environment

- Add only the official `gpiod` Python binding compatible with libgpiod v2; remove runtime reliance on `RPi.GPIO` for treadmill acquisition. Other behavior components may continue using gpiozero/RPi.GPIO, provided pin ownership is non-conflicting.
- Follow repository policy by using `uv` and `uv run` for all Python dependency and test commands. Because the repository currently has only `requirements_simple.txt`, decide whether to introduce `pyproject.toml`/`uv.lock` or document a system-package bridge before implementation. Do not mix ad hoc `pip` installs with the chosen environment.
- Verify the installed API from official docs and the actual installed package source on the Pi before writing the adapter. Pin a tested binding version after Pi 4/Pi 5 validation, not before.
- Do not add pandas, HDF5, or another logging dependency for this subsystem. CSV/JSON and the standard library are sufficient initially.
- Document OS packages, permissions/group membership for `/dev/gpiochip*`, and a capability-check command. Do not require root or real-time scheduling for the baseline.

Primary API/platform references to re-check during implementation:

- [libgpiod Python edge-event API](https://libgpiod.readthedocs.io/en/master/python_edge_event.html)
- [libgpiod v2.3 Python line-request API](https://libgpiod.readthedocs.io/en/v2.3/python_line_request.html)
- [libgpiod line settings and monotonic event clock](https://libgpiod.readthedocs.io/en/master/python_line_settings.html)
- [Raspberry Pi GPIO controller history and gpiochip numbering](https://pip-assets.raspberrypi.com/categories/685-whitepapers-app-notes-compliance-guides/documents/RP-006553-WP/A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices)

## 14. Strict test-first workflow

Each phase follows RED -> GREEN -> REFACTOR. Tests for a phase are committed before its implementation in a separate commit. The RED evidence (command, expected failures, and reason) is recorded in the commit message or implementation notes. Existing unrelated worktree changes are never included.

All local Python commands use the PyCharm-configured interpreter through `uv run`, after consulting the environment configuration. Hardware tests receive pytest markers such as `hardware`, `stress`, and `soak` so ordinary unit tests remain hardware-independent.

### 14.0 Terra Medium subagent execution protocol

Later implementation chats should use Terra Medium subagents for the bounded work packages in Section 15.8. A coordinating/root agent remains responsible for sequencing, repository inspection, user communication, integration review, and updating this plan. Subagents do not own broad phases or make unrecorded architectural decisions.

Every Terra Medium assignment must state:

- the work-package identifier and objective;
- prerequisite package/commit IDs that must already be complete;
- the exact files the subagent may inspect and the narrower files it may edit;
- public interfaces and data contracts that must remain unchanged;
- tests to add first and the expected RED failure;
- implementation deliverables allowed only after the RED test commit exists;
- commands required for focused and regression verification;
- performance/bounded-memory constraints relevant to the package;
- explicit non-goals and decisions that must be escalated rather than assumed;
- the required structured handoff report fields from Section 19.2.

Coordination rules:

1. Assign one small, independently reviewable work package at a time per subagent. Split a package further if a Terra Medium agent cannot reasonably hold its contracts and tests in context.
2. Parallel work is allowed only for packages with satisfied dependencies and disjoint edit ownership. Never assign two agents to edit the same file concurrently.
3. The coordinating agent must inspect each subagent's diff and evidence. A subagent report is not proof that tests passed or requirements were met.
4. Tests must be committed before implementation. The coordinating agent records the test commit ID and RED evidence in Section 19 before authorizing the GREEN task.
5. Implementation commits must not include unrelated changes or silently rewrite tests. Any genuine test correction or requirement change is separately justified and recorded.
6. A subagent must stop on unexpected worktree changes, ambiguous requirements, unsupported library behavior, or a needed public-interface change and return a blocker instead of guessing.
7. The coordinating agent updates the plan after every meaningful transition: assignment, RED commit, GREEN result, discovered decision, blocker, phase gate, and handoff/end of chat.
8. No phase is marked complete until its exit gate has been independently checked against repository state and recorded command output.

The preferred two-assignment rhythm for each code work package is:

```text
Terra Medium assignment A: inspect scope -> write tests only -> demonstrate RED
coordinator review and tests-only commit
Terra Medium assignment B: implement against committed tests -> demonstrate GREEN -> refactor
coordinator review, regression verification, implementation commit, plan-ledger update
```

The same Terra Medium subagent may receive assignment B after assignment A is reviewed, but test and implementation work remain separate assignments and commits.

### 14.1 Tests written first for Phase 1: config, state, pure decoder

1. Config accepts all valid boundary/default values and rejects same pins, invalid signs, nonpositive calibration/timeouts/rates/buffers, bad heartbeat relationships, and invalid policies.
2. Positive and negative one-cycle sequences yield exactly `+4` and `-4` transitions.
3. Partial cycles and sequences starting from all four AB states decode exactly.
4. Many cycles, long unidirectional traces, immediate/repeated reversals, and seeded randomized valid traces match a reference generator.
5. Position uses integer transitions; distance travelled is absolute; locomotion sign flips signed position/speed only.
6. Migration calibration derives exactly `0.1027375 mm/transition` from `0.41095 mm/cycle`.
7. Known synthetic speeds (including 10, 50, 100, and 500 mm/s where timestamps are integral/representable) use event timestamps, preserve sign, handle first transition, reverse direction, time out to zero, and retain last-edge speed.
8. Stationary, moving, repeated, and post-reversal zeroing reset reported origin while preserving lifetime position and every diagnostic.
9. Global/per-line gaps, duplicates, timestamp regression, zero `dt`, out-of-order sequence values, malformed channel/edge values, and invalid two-bit transitions follow the predeclared failure matrix.
10. Integrity and `FAILED` latch after loss and survive zero; explicit new acquisition state is required to clear them.
11. Diagnostic ring size remains bounded and lag histogram/summary calculations are correct.

### 14.2 Tests written first for Phase 2: GPIO adapter/resolution/synchronization

1. Capability probe accepts a complete v2-shaped fake and rejects each missing required feature with actionable text.
2. Resolver selects Pi 4 `pinctrl-bcm2711`, old/new-numbered Pi 5 `pinctrl-rp1`, and logs resolved paths/offsets.
3. Resolver rejects ambiguity, no candidate, missing/out-of-range pins, line ownership conflicts, and A/B on different controllers.
4. Adapter requests both lines together with input, both edges, monotonic clock, configured bias, explicit zero debounce, and requested kernel buffer.
5. Adapter converts binding events exactly and preserves kernel order/timestamps/sequence numbers.
6. Batch drain empties multiple batches before returning to lower-priority control work.
7. Initialization tests inject edges before request, after request, between drain/value read, during quiet wait, and at retry exhaustion; no event is applied twice or silently lost.
8. Backend errors release claimed lines and preserve underlying cause in the startup error.

### 14.3 Tests written first for Phase 3: shared state and multiprocessing

1. Readers never observe mismatched sentinel fields while a writer publishes repeatedly.
2. A reader deliberately paused while holding one slot cannot stop writer progress through the other slot.
3. Both slots held cause publication skips, not acquisition blocking; a later publication recovers freshness.
4. Snapshot timeout/staleness behavior is typed and never returns a torn state.
5. Start waits for `READY`, reports staged startup failures, times out cleanly, and releases all processes/resources.
6. Heartbeat updates without edges; stale heartbeat and killed acquisition process become effective `FAILED` rather than zero-speed `READY`.
7. Zero command is applied in the worker and acknowledgement matches command ID/version; queue saturation and timeout are explicit.
8. Graceful stop drains pending fake events, publishes final state, reaches `STOPPED`, joins, and remains idempotent across repeated stop/close.
9. Forced cleanup after an unresponsive worker is bounded and diagnosed.
10. Health-state transitions and all failure-policy outcomes are exact.

### 14.4 Tests written first for Phase 4: logger and file contracts

1. A fake monotonic clock produces nominal 200 Hz deadlines with monotonic actual timestamps.
2. Late cycles count missed deadlines and write one actual sample without catch-up duplicates.
3. CSV columns, units, enum encodings, JSON metadata, timebase anchors, JSONL diagnostic schema, and final summary are stable.
4. Writes occur in bounded chunks; memory remains bounded; normal close flushes all acknowledged samples.
5. A partially written/abnormally stopped file remains loadable through its last complete row.
6. Logger disk exceptions update logger status without blocking acquisition; required versus optional logger health outcomes differ as configured.
7. Ring-buffer failure dumps and optional raw-edge mode contain reconstructable before/after state and sequence data.
8. Repeated close is harmless and never overwrites a completed prior session file.

### 14.5 Tests written first for Phase 5: repository integration

1. `session_info` validates every treadmill field and detects conflicts with all enabled box GPIO assignments.
2. Output configuration creates the expected treadmill basename/sidecar paths without writing outside the session directory.
3. `Treadmill` delegates lifecycle/snapshot/zero/health without buffering edges.
4. Required treadmill initialization/start failure prevents behavior session startup.
5. Main-loop health checks map `warn`, approved `pause`, and `abort` outcomes correctly.
6. Every normal and exceptional cleanup path closes treadmill before session file transfer and preserves diagnostics.
7. Compatibility properties, if approved, have explicitly tested x1/x4 semantics and units.

### 14.6 Tests written first for Phase 6: volume and stress

1. Millions of seeded valid transitions with speed changes, pauses, bursts, and reversals decode to exact generated net/absolute totals with bounded memory.
2. Synthetic source -> real acquisition process -> shared state -> real logger remains exact while behavior executes CPU loops, disk I/O, console-like output, periodic sleeps, and GUI-like work.
3. Sequence gaps remain zero and integrity remains valid under representative load.
4. Injected gaps/process death/logger death produce the expected latched states and usable diagnostic artifacts.
5. Measure transitions/second, CPU, memory, publication skips, logging MB/hour, lag statistics, and backlog behavior; store results with software/config versions.

## 15. Implementation phases and commit gates

### Phase 0 — resolve requirements and establish environment

- Answer the open questions in Section 18.
- Choose non-conflicting pins and inspect actual encoder electrical characteristics.
- Record target Pi 4/Pi 5 OS, Python, kernel, and libgpiod versions.
- Decide uv project layout and verify the official binding on target hardware.
- Create a centralized GPIO allocation inventory.

Exit gate: decisions are documented and the implementation plan is approved. No code is written before this gate.

### Phase 1 — pure decoder

- Commit the Section 14.1 tests and confirm RED.
- Implement `config.py`, `state.py`, `quadrature.py`, and `diagnostics.py` incrementally with full data-contract docstrings; do not create a module until its tests require it.
- Run GREEN, refactor for clarity, then run the full non-hardware test suite.

Exit gate: exhaustive, randomized, speed, zero, failure-injection, and bounded-memory unit tests pass without GPIO or multiprocessing.

### Phase 2 — GPIO backend

- Commit Section 14.2 fake-backend/resolver/synchronization tests and confirm RED.
- Implement libgpiod capability probe, dynamic resolution, line request, synchronization, and batched event adaptation.
- Verify binding calls against installed package source and official documentation.
- Run a standalone marked Pi smoke test on Pi 4 and Pi 5 where available.

Exit gate: fake tests pass, both-edge events/sequence values are observed on hardware, ambiguous mapping fails closed, and startup races have deterministic coverage.

### Phase 3 — process isolation and public facade

- Commit Section 14.3 tests and confirm RED.
- Implement double-slot publication, acquisition worker, controls, heartbeat, health, startup, shutdown, and facade.
- Measure snapshot cost and publication-skip rate.

Exit gate: coherence and stalled-reader tests pass; acquisition death is detected; start/zero/stop/close are bounded and deterministic.

### Phase 4 — fixed-rate logging and diagnostics

- Commit Section 14.4 tests and confirm RED.
- Implement logger process, incremental CSV/JSON artifacts, diagnostic event stream, timebase anchors, failure dumps, and summary.
- Measure 200 Hz CPU and MB/hour on target Pi/storage.

Exit gate: timing/file/failure tests pass, memory stays bounded, abnormal output is recoverable to its last complete record, and logging never blocks acquisition.

### Phase 5 — behavior-stack migration

- Commit Section 14.5 tests and confirm RED.
- Update session config, `Treadmill` facade, `BehavBox`, `main.py`, cleanup, and documentation.
- Run the complete existing test suite and a debug session with a synthetic backend.

Exit gate: required failures stop session startup/run, clean shutdown precedes transfer, existing non-treadmill sessions behave unchanged, and no task consumes ambiguous raw counts.

### Phase 6 — synthetic acceptance and stress characterization

- Commit Section 14.6 tests/utilities and confirm RED where applicable.
- Run high-volume and real-process stress tests under representative behavior loads.
- Profile only if acceptance thresholds are missed; tune in the order specified by the requirements.

Exit gate: exact synthetic displacement, zero unexplained gaps, valid integrity, bounded memory, stable logger, and documented resource/storage results.

### Phase 7 — physical calibration and hardware acceptance

- Record encoder model/type/output voltage/output stage, external pulls, cycles/revolution if known, roller circumference, and wiring.
- Physically calibrate `mm_per_encoder_cycle` and determine `locomotion_sign`.
- Calculate maximum plausible transition rate and buffer headroom.
- Use a deterministic external quadrature source for 0.25x, 0.5x, 1x, and 2x rate sweeps under full representative behavior load; optionally characterize 4x.
- Test slow/fast motion, starts/stops, partial cycles, continuous direction, and rapid reversals.
- Run the actual full behavior stack.
- Run a soak for `max(2 hours, 1.5 * longest expected session)` while monitoring CPU, memory, disk, event rate, lag, and backlog.

Exit gate: at 2x maximum expected rate and through the soak, generated and decoded positions are exactly equal, sequence gaps and unexplained inconsistencies are zero, integrity is valid, processes/logging remain alive, and resources are stable.

### 15.8 Terra Medium work-package map

These are the default units of delegation. The coordinating agent may split a package into smaller numbered children, but must not merge packages in a way that bypasses a dependency or test-first commit gate.

| Package | Depends on | Terra Medium scope and primary files | Required output/evidence |
|---|---|---|---|
| `TM-0A` Decisions and environment inventory | Plan approval | Read-only inspection plus Section 18 answers; target Pi/OS/Python/libgpiod, encoder electronics, pins, session length, deployment source | Updated Sections 3, 13, 18, and 19; no implementation |
| `TM-0B` GPIO ownership inventory | `TM-0A` | Locate all GPIO allocations; plan centralized validation in `session_info.py`/new config without editing runtime code in the planning assignment | Approved pin map and conflict rules recorded in plan |
| `TM-1A` Config/public-state RED | `TM-0A`, `TM-0B` | Tests only for `config.py` and `state.py`; validation, enums, units, immutable public contracts and explicit-width conversion rules | Tests-only commit; focused `uv run pytest` output showing expected missing-implementation failures |
| `TM-1B` Config/public-state GREEN | `TM-1A` | Implement only `config.py`, `state.py`, and their data contracts | Focused GREEN plus affected regression tests; implementation commit |
| `TM-1C` Nominal quadrature RED/GREEN | `TM-1B` | Tests first, then `quadrature.py` edge/internal-state dataclasses and nominal x4 functions for calibration/sign, position/distance, speed, and zero offsets | Separate RED and GREEN commits; exhaustive starting-state evidence |
| `TM-1D` Integrity/diagnostics RED/GREEN | `TM-1C` | Failure-matrix tests, then sequence/state/timestamp checks, latching, lag aggregates, bounded ring | Separate commits; randomized/failure/bounded-memory evidence |
| `TM-2A` GPIO capability adapter | `TM-1D`, verified binding | Fake API tests first, then `gpio_backend.py` capability probe/event adaptation/line request | Binding-source reference recorded; RED/GREEN commits; no hardware-only assumptions |
| `TM-2B` GPIO resolver | `TM-2A` | Synthetic inventories and errors first, then cohesive resolver helpers within `gpio_backend.py` for Pi 4/Pi 5 dynamic resolution | Ambiguity/missing/claimed-line tests and actionable-error snapshots |
| `TM-2C` Startup synchronization and batch loop | `TM-2A`, `TM-2B` | Boundary-injection tests first, then race-safe synchronization and batch-drain primitive | Proof each boundary event is decoded once or explicitly excluded before READY |
| `TM-3A` Shared publication | `TM-1D` | Coherence/stalled-reader tests first, then `shared_state.py` double-slot publication | Stress evidence: no torn states and writer progress with stalled readers |
| `TM-3B` Acquisition lifecycle | `TM-2C`, `TM-3A` | Process/startup/heartbeat/death/shutdown tests first, then `acquisition.py` | Bounded lifecycle timings, staged errors, child cleanup evidence |
| `TM-3C` Controls, health, facade | `TM-3B` | Zero/queue/policy tests first, then `essential/treadmill_decoder.py` facade and typed outcomes | Ack/version evidence; effective-health and compatibility review |
| `TM-4A` Logger schemas and incremental writer | `TM-3A`, decisions in `TM-0A` | File-contract/partial-file tests first, then CSV/JSON/JSONL writer primitives | Stable schema fixtures, bounded-buffer and abnormal-file evidence |
| `TM-4B` Logger process and scheduler | `TM-3B`, `TM-4A` | Deadline/lateness/failure tests first, then `continuous_logger.py` process | 200 Hz simulated timing evidence; no catch-up duplicates/backpressure |
| `TM-4C` Diagnostic artifacts and summary | `TM-1D`, `TM-4B` | Event/failure-dump/summary tests first, then diagnostics integration | Reconstructable ring dump and complete summary fixture |
| `TM-5A` Session configuration integration | `TM-3C`, `TM-4C` | `session_info.py` tests first, then expanded config and centralized GPIO collision checks | Existing config regression plus conflict/error evidence |
| `TM-5B` Session facade migration | `TM-3C`, `TM-4C`, `TM-5A` | `essential/Treadmill.py` delegation/compatibility tests first, then removal of edge buffering | Proof no unbounded edge list/callback path remains |
| `TM-5C` Behavior lifecycle and failure policy | `TM-5B`, approved pause semantics | `essential/behavbox.py` and `main.py` startup/loop/cleanup tests first, then integration | Required failures stop safely; cleanup order and file-transfer evidence |
| `TM-5D` Operator/developer documentation | `TM-5C` | `docs/treadmill_setup.md` and `docs/treadmill_validation.md`; no runtime edits | Setup, calibration, health, recovery, tests, migration reviewed for fresh-user usability |
| `TM-6A` High-volume synthetic validation | `TM-1D`, `TM-3C` | Seeded millions-event utility/tests and resource measurement | Exact totals, seed/config/version, throughput and bounded-memory report |
| `TM-6B` Full process stress validation | `TM-4C`, `TM-5C`, `TM-6A` | Synthetic source through real processes/logger under representative loads | Exact totals, zero gaps, resource/storage/lag report and saved artifacts |
| `TM-7A` Hardware calibration utility/run | `TM-5D`, hardware available | `debug/treadmill_hardware_validate.py`, then physical calibration/sign/electrical record | Verified calibration and sign per rig; hardware metadata |
| `TM-7B` Rate sweep/full-stack/soak | `TM-6B`, `TM-7A` | External generator, actual behavior stack, resource monitoring, validation docs | 2x-rate acceptance and soak artifacts; final checklist evidence |

For packages shown as `RED/GREEN`, the coordinator must issue separate test and implementation assignments even though the row summarizes both. Hardware execution packages may require the coordinating agent or lab user to perform physical actions; Terra Medium should prepare commands/checklists and analyze returned evidence without inventing observations.

## 16. Performance strategy

Correctness and observability come first. Initial performance choices are:

- one acquisition process/interpreter;
- one joint A/B line request;
- batch draining rather than callbacks;
- fixed-size/slotted event/state structures where useful;
- publication after batches and heartbeat deadlines, not mandatory dataclass creation per edge;
- bounded deques/queues/buffers everywhere;
- integer transition accumulation and nanosecond timestamps;
- fixed-bin lag histogram rather than online percentile objects;
- chunked logger writes and no raw-edge disk stream by default;
- nonblocking shared-state publication and bounded control handling.

Do not add Numba, Cython, a C extension, real-time scheduling, or affinity preemptively. If representative profiling shows a bottleneck, first remove blocking/allocation, improve batching/buffers/publication, and only then seek approval for major optimization or scheduling changes.

## 17. Production acceptance checklist

Production approval requires a saved validation record showing:

- [ ] non-conflicting reviewed GPIO pin assignment;
- [ ] encoder electrical interface is safe for 3.3 V Pi GPIO;
- [ ] physical calibration and locomotion sign verified per rig;
- [ ] libgpiod capability/mapping metadata captured;
- [ ] all pure, failure, shared-state, logger, integration, volume, and process tests pass;
- [ ] both channels and both edge types are observed;
- [ ] kernel timestamps, not processing/wall time, drive speed;
- [ ] zero preserves lifetime diagnostics and integrity latch;
- [ ] worker death cannot appear as stationary `READY`;
- [ ] no behavior/logger backpressure path can block edge draining;
- [ ] 200 Hz record is incremental, bounded, aligned, and storage-measured;
- [ ] diagnostic log, failure dump, and final summary are interpretable;
- [ ] exact decoding at >=2x expected physical transition rate under full load;
- [ ] long full-stack soak passes with no loss, drift, failure, unbounded growth, or backlog;
- [ ] setup/calibration/operation/failure/migration documentation reviewed by another lab member.

## 18. Questions requiring user/lab decisions before implementation

1. Which two BCM pins should replace conflicting BCM17/27 on each rig, and are any other devices connected but not represented in `BehavBox`?
2. What are the encoder model, output voltage/output type, external pull resistors, roller circumference, and approximate maximum treadmill speed?
3. Which Raspberry Pi models and Raspberry Pi OS releases are mandatory, and what is the longest expected session duration?
4. Should a logger failure abort/pause the task (`continuous_logger_required=True`) or only degrade/warn as recommended here?
5. What must “pause” do operationally: freeze presenter/task progression until an operator explicitly restarts acquisition, end the current trial, or end the session safely?
6. Are any current or planned task modules consuming `treadmill.counts`, `distance_mm`, `speed_mms`, or `direction` outside the repository? This determines whether temporary compatibility aliases are necessary.
7. Is CSV interoperability required, or may the implementation switch to a compact binary record if measured 200 Hz CSV cost is too high?
8. May the repository adopt `pyproject.toml` and `uv.lock`, or must it retain `requirements_simple.txt` as the deployment source of truth?

Until these questions are answered, Phase 0 can gather environment/hardware facts, but implementation should not make assumptions that alter wiring, failure behavior, external API compatibility, or deployment.

## 19. Living implementation ledger and handoff protocol

This section must be updated throughout later development. It is not a retrospective changelog to fill in at the end. Its purpose is to let a fresh chat or Terra Medium subagent determine what is true now, what evidence exists, and what exact action is safe next.

### 19.1 Required update points

The coordinating agent updates this file:

1. before assigning a work package: mark it `IN PROGRESS`, record owner/model, date/chat, starting commit, allowed scope, and prerequisites checked;
2. after tests are written: record test files, focused command, expected/actual RED result, and tests-only commit ID;
3. before implementation: confirm the RED commit exists and record the implementation assignment/file ownership;
4. after implementation: record changed files, focused GREEN command/result, regression command/result, performance evidence, and implementation commit ID;
5. whenever a decision, deviation, newly discovered caller, hardware fact, or blocker appears;
6. at a phase exit: compare actual evidence with every exit criterion and mark `COMPLETE` only if all pass;
7. before ending or handing off a chat, even if work is incomplete: record the last known-good state and one exact next action.

Allowed status values are `NOT STARTED`, `IN PROGRESS`, `BLOCKED`, and `COMPLETE`. Never mark work complete based only on a subagent's narrative report. Link status to commits and reproducible command output. If work is uncommitted, say so explicitly and list the paths.

Plan maintenance is part of each work package's definition of done. Normally, the coordinating agent—not concurrent subagents—edits this ledger to avoid merge/conflicting edits. A phase's documentation update should be included in the corresponding tests-only or implementation commit when it accurately describes that commit; otherwise use a separate plan-only commit.

### 19.2 Work-package handoff record template

Copy this block under Section 19.4 for every started work package:

```markdown
#### TM-<phase/package>: <name>

- Status: NOT STARTED | IN PROGRESS | BLOCKED | COMPLETE
- Coordinator/chat/date:
- Terra Medium owner/assignment:
- Starting branch and commit:
- Prerequisites verified:
- Approved scope and editable files:
- Interfaces/contracts preserved:
- Tests added:
- RED command and result:
- Tests-only commit:
- Implementation files changed:
- GREEN command and result:
- Regression command and result:
- Performance/resource evidence:
- Implementation commit:
- Decisions/deviations and rationale:
- Newly discovered callers/risks:
- Blockers or unresolved questions:
- Working-tree state at handoff:
- Exact next action:
```

Do not write “tests pass” without the command and summarized result. Do not write “done” without commit IDs or an explicit explanation that work remains uncommitted. Hardware records must identify the rig/Pi, wiring/configuration, generator, rate, duration, software commit, and artifact paths.

### 19.3 Phase status summary

| Phase | Status | Evidence/commit | Next gate |
|---|---|---|---|
| Phase 0 — decisions/environment | `IN PROGRESS` (planning only) | This plan; no implementation commit | User answers Section 18 and approves plan |
| Phase 1 — pure decoder | `NOT STARTED` | None | `TM-1A` tests-only RED assignment |
| Phase 2 — GPIO backend | `NOT STARTED` | None | Phase 1 complete and target binding verified |
| Phase 3 — multiprocessing/shared state | `NOT STARTED` | None | Required Phase 2 and `TM-3A` prerequisites complete |
| Phase 4 — logger/diagnostics | `NOT STARTED` | None | Shared-state contracts stable |
| Phase 5 — behavior integration | `NOT STARTED` | None | Facade/logger stable and pause semantics approved |
| Phase 6 — synthetic stress | `NOT STARTED` | None | Integrated non-hardware system complete |
| Phase 7 — hardware acceptance | `NOT STARTED` | None | Hardware facts available and Phase 6 accepted |

### 19.4 Active and completed work-package records

No implementation work package has started. No Terra Medium implementation subagent has been assigned. No rewrite tests, implementation files, dependencies, or commits were created in the planning chat that produced this entry.

Current planning handoff:

- Status: planning in progress; implementation not started.
- Current artifact: `docs/treadmill_plan.md`.
- Latest design review: `docs/SoftwareDesign.md` was read on 2026-08-28. The proposed catch-all `models.py` and separate `gpio_resolution.py` were removed from the layout; data now stays with cohesive functions, the functional-core/composition/Protocol rules are explicit, and lower layers receive narrow dependencies rather than `session_info`.
- Known blocking facts: BCM17/27 conflict with existing behavior-box allocations; hardware/electrical/calibration/platform details and pause semantics are unresolved.
- Repository caution: the worktree contained unrelated user changes before/during planning; future agents must inspect and preserve them.
- Exact next action: user reviews this plan and answers Section 18. The plan is revised/approved in a planning-only chat before any `TM-1*` test or implementation assignment.
