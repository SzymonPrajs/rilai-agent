# Rilai v3 Architecture Overview

**Purpose:** Reference document for all implementation phases
**Execution:** Read-only reference, no code changes in this document

---

## MASTER IMPLEMENTATION CHECKLIST

> **IMPORTANT:** After completing any task from any document, update BOTH:
> 1. The checklist in the specific document (01-11)
> 2. This master checklist below
>
> Mark items with `[x]` when complete. Add date of completion in parentheses.

### Document Progress

- [ ] **01-contracts** - Event schemas and agent contracts
- [ ] **02-event-store** - EventLogWriter and projections
- [ ] **03-runtime-core** - TurnRunner and stages
- [ ] **04-workspace** - Workspace and reducer
- [ ] **05-agents** - Agent manifests and execution
- [ ] **06-deliberation** - Claim-based deliberation
- [ ] **07-council-voice** - Council and voice rendering
- [ ] **08-memory** - Memory system
- [ ] **09-tui** - TUI projection
- [ ] **10-daemon** - Brain daemon
- [ ] **11-migration** - Migration and cleanup

### Detailed Task Tracking

#### 01-contracts
- [ ] Create `src/rilai/contracts/__init__.py`
- [ ] Create `src/rilai/contracts/events.py` (EventKind, EngineEvent)
- [ ] Create `src/rilai/contracts/agent.py` (AgentOutput, Claim, AgentManifest)
- [ ] Create `src/rilai/contracts/sensor.py` (SensorOutput)
- [ ] Create `src/rilai/contracts/workspace.py` (StanceVector, GlobalModulators)
- [ ] Create `src/rilai/contracts/council.py` (CouncilDecision, SpeechAct)
- [ ] Create `src/rilai/contracts/memory.py` (MemoryCandidate, EpisodicEvent)
- [ ] Run tests for contracts

#### 02-event-store
- [ ] Create `src/rilai/store/__init__.py`
- [ ] Create `src/rilai/store/event_log.py` (EventLogWriter)
- [ ] Create `src/rilai/store/projections/__init__.py`
- [ ] Create `src/rilai/store/projections/base.py`
- [ ] Create `src/rilai/store/projections/turn_state.py`
- [ ] Create `src/rilai/store/projections/session.py`
- [ ] Create `src/rilai/store/projections/analytics.py`
- [ ] Create `src/rilai/store/projections/debug.py`
- [ ] Run tests for event store
- [ ] Delete v2 files: `memory/database.py`, `memory/short_term.py`, `observability/store.py`

#### 03-runtime-core
- [ ] Create `src/rilai/runtime/__init__.py`
- [ ] Create `src/rilai/runtime/turn_runner.py`
- [ ] Create `src/rilai/runtime/stages.py`
- [ ] Create `src/rilai/runtime/scheduler.py`
- [ ] Run tests for runtime core
- [ ] Delete v2 files: `core/engine.py`, `core/events.py`

#### 04-workspace
- [ ] Create `src/rilai/runtime/workspace.py`
- [ ] Create `src/rilai/runtime/reducer.py`
- [ ] Create `src/rilai/runtime/stance.py`
- [ ] Create `src/rilai/runtime/modulators.py`
- [ ] Run tests for workspace
- [ ] Delete v2 files: `core/stance.py`, `core/stance_aggregator.py`, `brain/modulators.py`

#### 05-agents
- [ ] Create `src/rilai/agents/__init__.py`
- [ ] Create `src/rilai/agents/manifest.py`
- [ ] Create `src/rilai/agents/base.py`
- [ ] Create `src/rilai/agents/executor.py`
- [ ] Create `src/rilai/agents/registry.py`
- [ ] Create example agent manifest (stress.yaml + stress.md)
- [ ] Run tests for agents
- [ ] Delete v2 files: `agents/protocol.py`, `agents/base.py` (old)
- [ ] Delete v2 folder: `agencies/`

#### 06-deliberation
- [ ] Create `src/rilai/runtime/deliberation.py`
- [ ] Create `src/rilai/runtime/argument_graph.py`
- [ ] Run tests for deliberation
- [ ] Delete v2 files: `council/deliberation.py`, `council/collector.py`

#### 07-council-voice
- [ ] Create `src/rilai/runtime/council.py`
- [ ] Create `src/rilai/runtime/voice.py`
- [ ] Create `src/rilai/runtime/critics.py`
- [ ] Run tests for council and voice
- [ ] Delete v2 files: `council/pipeline.py`, `council/synthesizer.py`, `council/voice.py`

#### 08-memory
- [ ] Create `src/rilai/memory/__init__.py`
- [ ] Create `src/rilai/memory/retrieval.py`
- [ ] Create `src/rilai/memory/episodic.py`
- [ ] Create `src/rilai/memory/user_model.py`
- [ ] Create `src/rilai/memory/consolidation.py`
- [ ] Create `src/rilai/memory/embeddings.py`
- [ ] Run tests for memory

#### 09-tui
- [ ] Create `src/rilai/ui/__init__.py`
- [ ] Create `src/rilai/ui/app.py`
- [ ] Create `src/rilai/ui/projection.py`
- [ ] Create `src/rilai/ui/panels/__init__.py`
- [ ] Create `src/rilai/ui/panels/chat.py`
- [ ] Create `src/rilai/ui/panels/sensors.py`
- [ ] Create `src/rilai/ui/panels/stance.py`
- [ ] Create `src/rilai/ui/panels/agents.py`
- [ ] Create `src/rilai/ui/panels/activity.py`
- [ ] Create `src/rilai/ui/panels/critics.py`
- [ ] Update `src/rilai/cli.py`
- [ ] Run tests for TUI
- [ ] Delete v2 folder: `tui/`

#### 10-daemon
- [ ] Create `src/rilai/daemon/__init__.py`
- [ ] Create `src/rilai/daemon/brain.py`
- [ ] Create `src/rilai/daemon/nudges.py`
- [ ] Create `src/rilai/daemon/decay.py`
- [ ] Run tests for daemon

#### 11-migration
- [ ] Backup v2 to branch
- [ ] Run database migration script
- [ ] Create all 49 agent prompts
- [ ] Delete remaining v2 files
- [ ] Run full integration tests
- [ ] Verify all success criteria

### Final Verification
- [ ] `rilai` command starts TUI with streaming updates
- [ ] `rilai shell` works with event-sourced pipeline
- [ ] All panels update in real-time
- [ ] Event log is replayable
- [ ] Background daemon emits proactive nudges
- [ ] Memory retrieval injects context before agents
- [ ] All 49+ agents output structured JSON
- [ ] No dual-write - single SQLite event log

---

## 1. Hard Invariants (Rules That Must Never Be Broken)

### Invariant A: One Turn = One Ordered Stream

Every turn produces an **append-only** sequence of events:
- `TurnStarted` → ... → `TurnCompleted`
- Strictly ordered (`seq` monotonic within turn)
- Drainable (no missed tail events)
- Replayable (can rebuild UI/state from the log)

```
Turn 1: [seq=0: TurnStarted] → [seq=1: SensorsFastUpdated] → ... → [seq=N: TurnCompleted]
Turn 2: [seq=0: TurnStarted] → [seq=1: SensorsFastUpdated] → ... → [seq=M: TurnCompleted]
```

### Invariant B: Single Source of Truth = Event Log

No "dual truth" (SQLite vs JSON).
- SQLite event log is the **only** authority
- All other state (projections, caches) is **derived**
- JSON cache is optional optimization, never authoritative

### Invariant C: Agents Only Write Proposals

Agents do **not** mutate global state directly. They output structured proposals:
- `observation` (what they noticed)
- `claims[]` (atomic statements)
- `stance_delta` (suggested changes)
- `workspace_patch` (suggested updates)
- `memory_candidates[]` (things to remember)

A deterministic **Workspace Reducer** merges proposals into actual state.

### Invariant D: UI Is a Projection, Never a Participant

The TUI never calls into engine internals. It only:
1. Consumes events from the stream
2. Updates its projection (TurnStateProjection)
3. Renders projection to widgets

---

## 2. Component Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              rilai-ui                                        │
│   ┌──────────────────────┐    ┌──────────────────────────────────────────┐  │
│   │   TurnStateProjection │◄───│  RilaiApp (Textual TUI)                  │  │
│   │   - apply_event()     │    │  - Sensors, Stance, Agents panels        │  │
│   │   - sensors, stance   │    │  - Workspace, Critics, Memory panels     │  │
│   │   - agent_logs        │    │  - Chat panel                            │  │
│   └──────────────────────┘    └──────────────────────────────────────────┘  │
│              ▲                                                               │
│              │ event stream (async iterator)                                 │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
┌──────────────┼───────────────────────────────────────────────────────────────┐
│              │                   rilai-runtime                                │
│   ┌──────────┴───────────┐                                                   │
│   │     TurnRunner       │◄── Main orchestrator, yields events               │
│   │  - run_turn()        │                                                   │
│   │  - 9 stages          │                                                   │
│   └──────────────────────┘                                                   │
│              │                                                               │
│   ┌──────────┼──────────────────────────────────────────────────────────┐   │
│   │          ▼                                                           │   │
│   │   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │   │
│   │   │ Scheduler  │  │ Workspace  │  │Deliberator │  │  Council   │   │   │
│   │   │(agent pick)│  │(blackboard)│  │(claims)    │  │(decision)  │   │   │
│   │   └────────────┘  └────────────┘  └────────────┘  └────────────┘   │   │
│   │          │               │              │              │            │   │
│   │          ▼               ▼              ▼              ▼            │   │
│   │   ┌────────────────────────────────────────────────────────────┐   │   │
│   │   │                    Workspace Reducer                        │   │   │
│   │   │  - merge proposals deterministically                        │   │   │
│   │   │  - update stance (leaky integrator)                         │   │   │
│   │   │  - update modulators                                        │   │   │
│   │   └────────────────────────────────────────────────────────────┘   │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│              │                                                               │
└──────────────┼───────────────────────────────────────────────────────────────┘
               │
┌──────────────┼───────────────────────────────────────────────────────────────┐
│              │                   rilai-store                                  │
│   ┌──────────┴───────────┐                                                   │
│   │   EventLogWriter     │◄── Single-writer append-only log                  │
│   │  - append(event)     │                                                   │
│   │  - replay_turn()     │                                                   │
│   └──────────────────────┘                                                   │
│              │                                                               │
│              ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        SQLite: events table                          │   │
│   │   (session_id, turn_id, seq, ts, kind, payload_json)                 │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│              │                                                               │
│              ▼                                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                         Projections                                  │   │
│   │  - TurnStateProjection (for TUI)                                     │   │
│   │  - SessionProjection (conversation history)                          │   │
│   │  - AnalyticsProjection (tokens, latency)                             │   │
│   │  - DebugProjection (agent traces)                                    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘
               │
┌──────────────┼───────────────────────────────────────────────────────────────┐
│              │                   rilai-contracts                              │
│   ┌──────────┴───────────┐                                                   │
│   │  All typed schemas   │◄── Pydantic models, versioned                     │
│   │  - EngineEvent       │                                                   │
│   │  - AgentOutput       │                                                   │
│   │  - Claim             │                                                   │
│   │  - CouncilDecision   │                                                   │
│   │  - StanceVector      │                                                   │
│   └──────────────────────┘                                                   │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure (v3)

```
src/rilai/
├── __init__.py
├── cli.py                        # Entry point (MODIFIED from v2)
│
├── contracts/                    # NEW: All schemas
│   ├── __init__.py
│   ├── events.py                 # EngineEvent, EventKind enum
│   ├── agent.py                  # AgentOutput, AgentManifest, Claim
│   ├── sensor.py                 # SensorOutput
│   ├── workspace.py              # WorkspaceState, StanceVector, GlobalModulators
│   ├── council.py                # CouncilDecision, SpeechAct, VoiceResult
│   └── memory.py                 # MemoryCandidate, EpisodicEvent, UserFact
│
├── store/                        # NEW: Event log + projections
│   ├── __init__.py
│   ├── event_log.py              # EventLogWriter (append-only)
│   └── projections/
│       ├── __init__.py
│       ├── base.py               # Projection base class
│       ├── turn_state.py         # TurnStateProjection (for TUI)
│       ├── session.py            # SessionProjection
│       ├── analytics.py          # AnalyticsProjection
│       └── debug.py              # DebugProjection
│
├── runtime/                      # NEW: TurnRunner and stages
│   ├── __init__.py
│   ├── turn_runner.py            # Main orchestrator
│   ├── stages.py                 # Stage implementations
│   ├── scheduler.py              # Agent scheduling with budgets
│   ├── workspace.py              # Workspace (blackboard)
│   ├── reducer.py                # Deterministic proposal merger
│   ├── stance.py                 # StanceVector management
│   ├── modulators.py             # GlobalModulators with decay
│   ├── deliberation.py           # Deliberator class
│   ├── argument_graph.py         # Claim graph
│   ├── council.py                # Council decision logic
│   ├── voice.py                  # Voice renderer
│   └── critics.py                # Post-generation critics
│
├── agents/                       # REWRITTEN: Manifest-based
│   ├── __init__.py
│   ├── manifest.py               # AgentManifest schema
│   ├── base.py                   # BaseAgent class
│   ├── executor.py               # Parallel agent execution
│   └── registry.py               # Load manifests from YAML
│
├── memory/                       # REWRITTEN: Full memory system
│   ├── __init__.py
│   ├── retrieval.py              # Memory retrieval before agents
│   ├── episodic.py               # Episodic event storage
│   ├── user_model.py             # User facts/preferences
│   └── consolidation.py          # Memory consolidation
│
├── daemon/                       # NEW: Background brain
│   ├── __init__.py
│   ├── brain.py                  # Background tick loop
│   ├── nudges.py                 # Proactive suggestion logic
│   └── decay.py                  # Modulator decay
│
├── ui/                           # REWRITTEN: Projection-based
│   ├── __init__.py
│   ├── app.py                    # Main Textual app
│   ├── projection.py             # TurnStateProjection
│   └── panels/                   # Individual panel widgets
│       ├── __init__.py
│       ├── sensors.py
│       ├── stance.py
│       ├── agents.py
│       ├── workspace.py
│       ├── critics.py
│       ├── memory.py
│       └── chat.py
│
├── providers/                    # KEPT: OpenRouter
│   ├── __init__.py
│   └── openrouter.py             # LLM provider (minor updates)
│
└── config/                       # KEPT: Configuration
    ├── __init__.py
    ├── defaults.py
    └── loader.py

prompts/                          # REDESIGNED: All 49+ agents
├── agents/
│   ├── emotion/
│   │   ├── stress.yaml           # Agent manifest
│   │   └── stress.md             # Prompt template
│   │   ├── wellbeing.yaml
│   │   └── wellbeing.md
│   │   └── ...
│   ├── planning/
│   ├── social/
│   ├── reasoning/
│   ├── creative/
│   ├── inhibition/
│   ├── monitoring/
│   ├── execution/
│   ├── resource/
│   └── self/
├── council/
│   ├── synthesizer.md
│   └── voice.md
└── critics/
    ├── safety_policy.md
    ├── coherence.md
    ├── over_advice.md
    └── tone_mismatch.md
```

---

## 4. Event Flow Diagram

```
User types: "I'm feeling overwhelmed"
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 0: INGEST                                                      │
│   emit: TurnStarted {user_input, turn_id}                           │
│   emit: TurnStageChanged {stage: "ingest"}                          │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 1: FAST SENSORS                                               │
│   emit: TurnStageChanged {stage: "sensing_fast"}                    │
│   Run deterministic keyword extraction                               │
│   emit: SensorsFastUpdated {sensors: {vulnerability: 0.8, ...}}     │
│   IF safety_risk > 0.8 → emit SafetyInterrupt, skip to Council      │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 2: CONTEXT BUILD                                              │
│   emit: TurnStageChanged {stage: "context"}                         │
│   Retrieve episodic events, user facts, open threads                │
│   emit: WorkspacePatched {patch: {retrieved_episodes: [...]}}       │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 3-4: AGENT WAVES                                              │
│   emit: TurnStageChanged {stage: "agents"}                          │
│                                                                      │
│   Wave 1: Always-on (censor, trigger_watcher, anomaly_detector)     │
│     FOR each agent:                                                  │
│       emit: AgentStarted {agent_id}                                 │
│       Run LLM call                                                   │
│       emit: AgentCompleted {agent_id, observation, claims, ...}     │
│     Reducer merges proposals                                         │
│     emit: WorkspacePatched {patch: ...}                             │
│     emit: StanceUpdated {delta: ...}                                │
│                                                                      │
│   Wave 2: Scheduled agents (based on sensors + modulators)          │
│     (same pattern as Wave 1)                                         │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 5: DELIBERATION                                               │
│   emit: TurnStageChanged {stage: "deliberation"}                    │
│   emit: DelibRoundStarted {round: 0}                                │
│   Build argument graph from claims                                   │
│   Compute consensus                                                  │
│   emit: ConsensusUpdated {level: 0.85}                              │
│   IF consensus < 0.5 AND critical claims:                           │
│     Request focused follow-ups                                       │
│     emit: DelibRoundStarted {round: 1}                              │
│     ...                                                              │
│   emit: DelibRoundCompleted {round: N, final_consensus: 0.9}        │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 6: COUNCIL + VOICE                                            │
│   emit: TurnStageChanged {stage: "council"}                         │
│   Council LLM synthesizes decision from workspace + claims          │
│   emit: CouncilDecisionMade {speak: true, urgency: "medium", ...}   │
│   Voice LLM renders speech_act to natural language                  │
│   emit: VoiceRendered {text: "I hear you. Work stress can..."}      │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 7: CRITICS                                                    │
│   emit: TurnStageChanged {stage: "critics"}                         │
│   Run post-generation validators                                    │
│   emit: CriticsUpdated {results: [{critic: "safety", passed: true}]}│
│   IF safety_policy fails → regenerate or block                      │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Stage 8: MEMORY COMMIT                                              │
│   emit: TurnStageChanged {stage: "memory_commit"}                   │
│   Select durable updates from memory_candidates                     │
│   Create episodic event if significant                              │
│   Update user model hypotheses                                      │
│   emit: MemoryCommitted {summary: {...}}                            │
└─────────────────────────────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ TURN COMPLETE                                                       │
│   emit: TurnCompleted {total_time_ms: 850, response: "I hear..."}   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 5. Key Event Kinds

| Category | Event Kind | Payload |
|----------|-----------|---------|
| **Turn Lifecycle** | `TURN_STARTED` | `{user_input, turn_id}` |
| | `TURN_STAGE_CHANGED` | `{stage}` |
| | `TURN_COMPLETED` | `{total_time_ms, response}` |
| **Sensors** | `SENSORS_FAST_UPDATED` | `{sensors: {name: prob}}` |
| **Agents** | `AGENT_STARTED` | `{agent_id}` |
| | `AGENT_COMPLETED` | `{agent_id, observation, claims, ...}` |
| | `AGENT_FAILED` | `{agent_id, error}` |
| **Workspace** | `WORKSPACE_PATCHED` | `{patch: {...}}` |
| | `STANCE_UPDATED` | `{delta: {...}}` |
| **Deliberation** | `DELIB_ROUND_STARTED` | `{round}` |
| | `DELIB_ROUND_COMPLETED` | `{round, consensus}` |
| | `CONSENSUS_UPDATED` | `{level}` |
| **Council** | `COUNCIL_DECISION_MADE` | `{speak, urgency, speech_act}` |
| | `VOICE_RENDERED` | `{text}` |
| **Critics** | `CRITICS_UPDATED` | `{results: [...]}` |
| | `SAFETY_INTERRUPT` | `{reason}` |
| **Memory** | `MEMORY_COMMITTED` | `{summary}` |
| **Daemon** | `DAEMON_TICK` | `{timestamp}` |
| | `PROACTIVE_NUDGE` | `{reason, suggestion}` |
| | `MODULATORS_DECAYED` | `{modulators}` |

---

## 6. v2 → v3 Conceptual Mapping

| v2 Concept | v3 Replacement |
|------------|----------------|
| `EventBus` (pub/sub) | Direct `AsyncIterator[EngineEvent]` |
| `Engine.process_message()` | `TurnRunner.run_turn()` |
| `AgencyRunner` | `Scheduler` + `AgentExecutor` |
| `GenericAgency` | Agent manifests (YAML) |
| `[U:C]` salience suffix | Structured `AgentOutput.urgency/confidence` |
| Dual-write (SQLite + JSON) | Single `EventLogWriter` |
| `Store` class | `EventLogWriter` + `Projections` |
| `RealEngine` adapter | `TurnStateProjection` |
| `_apply_event()` per kind | `projection.apply_event()` |
| Batch panel updates at end | Streaming updates per event |
| No daemon | `BrainDaemon` with ticks |

---

## 7. Implementation Dependencies

```
01-contracts       ← Foundation, no dependencies
        │
        ▼
02-event-store     ← Depends on contracts
        │
        ▼
03-runtime-core    ← Depends on contracts, store
        │
        ├────────────────────────────────────┐
        ▼                                    ▼
04-workspace                            05-agents
        │                                    │
        └────────────┬───────────────────────┘
                     ▼
             06-deliberation
                     │
                     ▼
             07-council-voice
                     │
                     ▼
               08-memory
                     │
                     ▼
                 09-tui
                     │
                     ▼
               10-daemon
                     │
                     ▼
             11-migration
```

---

## 8. Success Criteria

After v3 implementation is complete:

1. **`rilai` command** starts TUI with streaming panel updates
2. **`rilai shell`** works with event-sourced pipeline
3. **All panels update in real-time** (not batched at end)
4. **Event log is replayable** - can rebuild UI state from events
5. **Background daemon** emits proactive nudges
6. **Memory retrieval** injects context before agents run
7. **All 49+ agents** output structured JSON
8. **No dual-write** - single SQLite event log is source of truth

---

*This document is read-only reference. Proceed to `01-contracts.md` for first implementation.*
