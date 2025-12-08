# Rilai v3 Architecture Overview

**Purpose:** Reference document for all implementation phases
**Execution:** Read-only reference, no code changes in this document

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
