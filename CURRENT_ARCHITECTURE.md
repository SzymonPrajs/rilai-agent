# Rilai v2 - Complete System Architecture Document

**Purpose:** Comprehensive technical reference for refactoring and cleanup
**Status:** Current state as of latest changes

---

## 1. PROJECT OVERVIEW

### What Is Rilai v2?

Rilai v2 is a **cognitive architecture for AI companionship** - an always-on multi-agent system that mirrors aspects of human cognition. Named after Riley from Inside Out, who had a council of emotions in her head.

**Core Philosophy:** Instead of a single monolithic LLM call, Rilai uses a "Society of Mind" where 49+ specialized agents (organized into 10 agencies) deliberate on every user message, and a Council synthesizes their assessments into a response.

### Key Design Goals

1. **Multi-perspective reasoning** - Different agents see different aspects of user messages
2. **Multi-round deliberation** - Agents can hear each other and adjust positions
3. **Transparent cognition** - All agent outputs visible for debugging
4. **Thinking model support** - Native extraction of reasoning tokens
5. **Real-time observability** - TUI displays agent activity as it happens

---

## 2. HIGH-LEVEL ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TEXTUAL TUI                                    │
│  ┌─────────────────────────────────┬──────────────────────────────────┐ │
│  │         CHAT PANEL              │        INSPECTOR PANEL           │ │
│  │                                 │  ┌──────────────────────────┐   │ │
│  │  User: ...                      │  │ Status: MODE | GOAL | TIER │   │ │
│  │  Rilai: ...                     │  ├──────────────────────────┤   │ │
│  │                                 │  │ TABS:                    │   │ │
│  │                                 │  │ • Sensors (probabilities)│   │ │
│  │                                 │  │ • Stance (8 dimensions)  │   │ │
│  │                                 │  │ • Agents (salience)      │   │ │
│  │                                 │  │ • Workspace (goal/plan)  │   │ │
│  │                                 │  │ • Critics (validation)   │   │ │
│  │                                 │  │ • Memory (hypotheses)    │   │ │
│  └─────────────────────────────────┴──────────────────────────────────┘ │
│  [Input] _____________________________ [Send] [Play] [Clear] [Mic]      │
│  Activity: IDLE | SENSING | THINKING | SPEAKING                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           REAL ENGINE ADAPTER                            │
│  - Bridges Core Engine to TUI                                           │
│  - Subscribes to event_bus events                                       │
│  - Queues EngineEvents for streaming to TUI                             │
│  - Yields events as async generator                                      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              CORE ENGINE                                 │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────────────────┐│
│  │   10 AGENCIES  │→ │  DELIBERATION  │→ │   COUNCIL + VOICE          ││
│  │   (49 agents)  │  │  (0-3 rounds)  │  │   (synthesis + render)     ││
│  └────────────────┘  └────────────────┘  └────────────────────────────┘│
│              │                │                      │                  │
│              ▼                ▼                      ▼                  │
│  ┌────────────────────────────────────────────────────────────────────┐│
│  │                    OBSERVABILITY STORE                              ││
│  │           (Dual-write to SQLite + JSON)                             ││
│  └────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          OPENROUTER PROVIDER                             │
│  - Thinking model support (DeepSeek R1, Claude :thinking, o1/o3)        │
│  - Automatic reasoning token extraction                                  │
│  - Groq fast inference for small models                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. PROCESSING PIPELINE (What Happens Each Turn)

```
User Input: "I'm feeling overwhelmed with work"
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 1: Store & Initialize                                             │
│   store.add_message("user", input)                                     │
│   turn_context = store.start_turn(input)                               │
│   emit EVENT: PROCESSING_STARTED                                       │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 2: Build Context Objects                                          │
│   RilaiEvent: {event_id, type, content, user_id, session_id, ts}      │
│   WorkingMemoryView: {conversation_history, goals, assessments}        │
│   EventSignature: {emotion_markers, planning_markers, ...}             │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 3: Run ALL 10 Agencies in Parallel                                │
│   AgencyRunner.run_all_traced() with max_parallel=7                    │
│                                                                        │
│   For each agency:                                                     │
│     1. Gate agents (domain markers + modulators + cooldown)            │
│     2. Run gated agents in parallel (asyncio.gather)                   │
│     3. Each agent returns: {voice, salience, thinking, trace}          │
│     4. Compress outputs (filter to high-salience, top_k=3)             │
│                                                                        │
│   emit EVENTS: AGENCY_STARTED, AGENT_STARTED, AGENT_COMPLETED          │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 4: Collect Assessments                                            │
│   CollectedAssessments: organize by agency + all_agents list           │
│   Track: highest_urgency, top_salient agents                           │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 5: Multi-Round Deliberation (if enabled)                          │
│                                                                        │
│   Round 0: Initial positions (independent assessment)                  │
│   Round 1-N: Agents see others' voices, can:                           │
│     - "maintain" (keep position)                                       │
│     - "adjust" (modify based on others)                                │
│     - "defer" (yield to another agent)                                 │
│     - "dissent" (disagree explicitly)                                  │
│                                                                        │
│   Early Exit Conditions:                                               │
│     - Critical urgency (U=3) in round 0                                │
│     - Consensus >= 0.9 AND speaking_pressure >= 0.5                    │
│     - All agents deferred                                              │
│     - Max rounds (3) reached                                           │
│                                                                        │
│   emit EVENTS: DELIBERATION_ROUND_STARTED, DELIBERATION_ROUND_COMPLETED│
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 6: Council Synthesis                                              │
│   Synthesizer LLM call with:                                           │
│     - User input (prominently displayed)                               │
│     - All agent observations with [U:C] salience metadata              │
│     - Deliberation round count + consensus level                       │
│                                                                        │
│   Output: CouncilDecision {                                            │
│     speak: bool,                                                       │
│     urgency: "low" | "medium" | "high" | "critical",                   │
│     speech_act: {intent, key_points, tone, do_not},                    │
│     thinking: str (reasoning trace)                                    │
│   }                                                                    │
│                                                                        │
│   emit EVENT: COUNCIL_DECISION                                         │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 7: Voice Rendering (if speak=True)                                │
│   Voice LLM transforms speech_act → natural language                   │
│   Uses self_model (name, tone_defaults, boundaries)                    │
│   Output: VoiceResult {message, processing_time_ms}                    │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 8: Build TUI State                                                │
│   stance = aggregate_stance(collected)        # 8 dimensions           │
│   sensors = extract_sensors(event)            # Fast deterministic     │
│   workspace = build_workspace(council, coll)  # Goal/constraints       │
│   memory = extract_memory(store)              # Context summary        │
│   critics = run_critics(response, input)      # Validation checks      │
│                                                                        │
│   turn_state = TurnState(stance, sensors, agents, workspace, ...)      │
└───────────────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ STEP 9: Return Result                                                  │
│   store.end_turn(council_speak, urgency, response)                     │
│   emit EVENT: PROCESSING_COMPLETED                                     │
│   return EngineResult {response, turn_state}                           │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 4. SOCIETY OF MIND: 10 AGENCIES, 49+ AGENTS

### Agency Hierarchy

```
COUNCIL (synthesis layer)
│
├── GOAL-ORIENTED (3 agencies, 13 agents)
│   │
│   ├── PLANNING AGENCY (4 agents)
│   │   ├── difference_engine  - Gap analysis (current vs desired state)
│   │   ├── short_term         - Immediate next steps
│   │   ├── long_term          - Strategic direction
│   │   └── priority           - Urgency triage
│   │
│   ├── RESOURCE AGENCY (3 agents)
│   │   ├── financial          - Money/budget awareness
│   │   ├── time               - Time pressure assessment
│   │   └── energy             - Cognitive/emotional energy
│   │
│   └── SELF AGENCY (6 agents)
│       ├── identity           - Core self-concept consistency
│       ├── values             - Value alignment checking
│       ├── meta_monitor       - Self-awareness of reasoning
│       ├── attachment_learner - Learning user attachment style
│       ├── reflection         - Deep introspection
│       └── self_model         - Rilai's self-concept (name, tone, boundaries)
│
├── EVALUATIVE (2 agencies, 10 agents)
│   │
│   ├── EMOTION AGENCY (5 agents)
│   │   ├── wellbeing          - User emotional state
│   │   ├── stress             - Stress/overwhelm detection (ALWAYS-ON)
│   │   ├── motivation         - Drive/engagement levels
│   │   ├── mood_regulator     - Affect modulation
│   │   └── wanting            - Desire/craving detection
│   │
│   └── SOCIAL AGENCY (5 agents)
│       ├── relationships      - Relationship dynamics
│       ├── empathy            - Perspective-taking
│       ├── norms              - Social appropriateness
│       ├── attachment_detector- Attachment style recognition
│       └── mental_model       - Theory of mind for user
│
├── PROBLEM-SOLVING (2 agencies, 9 agents)
│   │
│   ├── REASONING AGENCY (6 agents)
│   │   ├── debugger           - Error/inconsistency detection
│   │   ├── researcher         - Information gathering needs
│   │   ├── reformulator       - Reframing problems
│   │   ├── analogizer         - Finding similar patterns
│   │   ├── creative           - Novel approaches
│   │   └── magnitude          - Scale/impact assessment
│   │
│   └── CREATIVE AGENCY (3 agents)
│       ├── brainstormer       - Divergent thinking
│       ├── synthesizer        - Combining ideas
│       └── frame_builder      - New perspective frames
│
├── CONTROL (2 agencies, 7 agents)
│   │
│   ├── INHIBITION AGENCY (3 agents)
│   │   ├── censor             - Inappropriate content blocking (ALWAYS-ON)
│   │   ├── suppressor         - Impulse control
│   │   └── exception_handler  - Error handling (ALWAYS-ON)
│   │
│   └── MONITORING AGENCY (4 agents)
│       ├── trigger_watcher    - Trigger detection (ALWAYS-ON)
│       ├── anomaly_detector   - Unusual pattern detection (ALWAYS-ON)
│       ├── interrupt_manager  - Interrupt handling
│       └── attention          - Focus management
│
└── ACTION (1 agency, 6 agents)
    │
    └── EXECUTION AGENCY (6 agents)
        ├── executor           - Task execution planning
        ├── habits             - Routine behavior patterns
        ├── script_runner      - Pre-programmed responses
        ├── context_manager    - Context switching
        ├── output_filter      - Response filtering
        └── general_responder  - Default response generation
```

### Agent Gating Logic

```python
# Always-on agents (never gated, interrupt-capable)
ALWAYS_ON = {"censor", "exception_handler", "trigger_watcher", "anomaly_detector", "stress"}

# Gating factors:
1. Domain markers from EventSignature:
   - emotion_markers → emotion agency
   - planning_markers → planning, resource agencies
   - social_markers → social agency
   - problem_markers → reasoning, creative agencies
   - action_markers → execution agency

2. Question events → activate reasoning + creative

3. Modulator thresholds:
   - arousal > 0.7 → activate monitoring
   - time_pressure > 0.5 → activate planning
   - social_risk > 0.5 → activate social, inhibition

4. Cooldown filtering (agents get 30s cooldown after firing)

5. Budget limiting (max_agents_per_cycle, default unlimited)
```

---

## 5. SENSOR SYSTEM

### What Sensors Do

Sensors provide **probabilistic classification** of user intent/state. They are "boxed" LLM calls that see only the user message, not full context.

### 9 Core Sensors

| Sensor | Purpose | Output Range |
|--------|---------|--------------|
| `vulnerability` | Fear/shame/sadness detection | 0.0-1.0 |
| `advice_requested` | Explicit solution-seeking | 0.0-1.0 |
| `relational_bid` | "Do you care about me?" probes | 0.0-1.0 |
| `ai_feelings_probe` | Questions about AI sentience | 0.0-1.0 |
| `humor_masking` | Deflecting with humor | 0.0-1.0 |
| `rupture` | Disappointment/withdrawal | 0.0-1.0 |
| `ambiguity` | Unclear intent | 0.0-1.0 |
| `safety_risk` | Self-harm/violence | 0.0-1.0 |
| `prompt_injection` | Manipulation attempts | 0.0-1.0 |

### Sensor Output Structure

```python
@dataclass
class SensorOutput:
    sensor: str                          # Sensor name
    p: float                             # Probability [0.0-1.0]
    evidence: list[EvidenceSpan]         # Supporting text spans
    counterevidence: list[EvidenceSpan]  # Contrary text spans
    notes: str                           # Max 12 words observation
```

### Two Sensor Paths

1. **Full Sensor Ensemble** (slow, accurate)
   - File: `src/rilai/sensors/runner.py`
   - Runs 2x redundancy per sensor
   - Uses "tiny" model for speed
   - Full LLM classification

2. **Fast Sensor Extraction** (instant, deterministic)
   - File: `src/rilai/core/sensor_extractor.py`
   - Uses EventSignature markers
   - No LLM call required
   - Used for immediate TUI display

---

## 6. MODULATOR SYSTEM

### GlobalModulators (System-Wide Affective Signals)

```python
@dataclass
class GlobalModulators:
    arousal: float        # [0.0-1.0] calm → activated
    fatigue: float        # [0.0-1.0] rested → exhausted
    time_pressure: float  # [0.0-1.0] relaxed → urgent
    social_risk: float    # [0.0-1.0] safe → high stakes
    last_update: datetime
    source_agents: dict   # Which agent last updated each
```

**Modulator Decay:** Each tick, modulators decay toward 0.5 baseline by factor 0.9

**Modulator Inference Map:**
```python
MODULATOR_MAP = {
    "emotion.stress": ("arousal", 0.3, False),      # Stress → arousal UP
    "emotion.wellbeing": ("fatigue", 0.3, True),    # Wellbeing → fatigue DOWN
    "resource.time": ("time_pressure", 0.3, False), # Time agent → pressure UP
    "social.norms": ("social_risk", 0.3, False),    # Norms → risk UP
    "inhibition.censor": ("social_risk", 0.2, False),
}
```

### AgentActivationState (Per-Agent Scheduling)

```python
@dataclass
class AgentActivationState:
    agent_id: str
    last_fired: datetime | None
    cooldown_until: datetime | None
    rolling_salience: float              # Exponential moving average
    fire_count: int
    archetype_weight: float              # Interrupt=1.5x, Monitor=1.3x, Verbose=0.9x
```

---

## 7. STATE MANAGEMENT

### Stance Vector (Persistent Affective State)

**NOT a claim of human emotion** - Internal modulation state for response generation.

```python
@dataclass
class StanceVector:
    # Core affective (PAD model)
    valence: float      # [-1, 1] unpleasant → pleasant
    arousal: float      # [0, 1] calm → activated
    control: float      # [0, 1] helpless → dominant

    # Cognitive-social modulators
    certainty: float    # [0, 1] confused → clear
    safety: float       # [0, 1] threatened → secure
    closeness: float    # [0, 1] distant → connected
    curiosity: float    # [0, 1] saturated → wondering
    strain: float       # [0, 1] ease → overload

    # Metadata
    turn_id: int
    last_update_ts: float
    notes: list[str]    # Max 6 style notes
```

**Derived Quantities:**
- `readiness_to_speak` - How ready to generate response
- `advice_suppression` - How much to suppress unsolicited advice
- `exploration_bias` - Explore vs exploit ratio
- `warmth_level` - Tone warmth

**Update Dynamics:**
- Leaky integrator with alpha=0.25
- Max delta ±0.15 per dimension per turn
- Prevents thrashing while allowing gradual evolution

### TurnState (Complete TUI Data)

```python
@dataclass
class TurnState:
    turn_id: int
    stance: dict          # 8 dimensions + derived quantities
    sensors: dict         # sensor_name → probability
    agents: list[dict]    # {agent_id, salience, glimpse, ...}
    workspace: dict       # {goal, primary_question, constraints, ...}
    critics: list[dict]   # {critic, passed, reason, severity}
    memory: dict          # {summary, evidence, hypotheses}

@dataclass
class EngineResult:
    response: str
    turn_state: TurnState
```

---

## 8. STORAGE LAYER (Dual-Write)

### SQLite Database (Permanent)

**File:** `src/rilai/memory/database.py`

| Table | Purpose |
|-------|---------|
| `sessions` | Session lifecycle |
| `messages` | Conversation history |
| `turns` | User input + response pairs |
| `agent_calls` | Individual agent outputs + thinking |
| `model_calls` | API calls with token tracking |
| `council_calls` | Council deliberation results |
| `deliberation_rounds` | Multi-round traces |

### JSON Short-Term Memory (Ephemeral)

**File:** `src/rilai/memory/short_term.py`

```
data/current/
├── session.json          # Current session metadata
├── messages.json         # All conversation messages
├── turns/
│   └── {turn_id}.json    # Per-turn trace
└── agents/
    └── {agent_id}.json   # Per-agent firing history (last 50)
```

### Observability Store (Unified Interface)

**File:** `src/rilai/observability/store.py`

```python
class Store:
    """Writes to BOTH SQLite and JSON."""

    def __init__(self, enable_sqlite=True, enable_json=True):
        self.db: Database        # SQLite
        self.stm: ShortTermMemory  # JSON

    # All operations write to both backends
```

---

## 9. EVENT BUS (Signal Propagation)

**File:** `src/rilai/core/events.py`

### EventBus API

```python
class EventBus:
    async def emit(event: Event)      # Async queue
    async def emit_now(event: Event)  # Wait for handlers
    def subscribe(type, handler)       # Register handler
    def unsubscribe(type, handler)    # Remove handler
```

### Key Event Types

| Category | Events |
|----------|--------|
| Session | `SESSION_STARTED`, `SESSION_ENDED` |
| Processing | `PROCESSING_STARTED`, `PROCESSING_COMPLETED` |
| Agency | `AGENCY_STARTED`, `AGENCY_COMPLETED` |
| Agent | `AGENT_STARTED`, `AGENT_COMPLETED` |
| Deliberation | `DELIBERATION_ROUND_STARTED`, `DELIBERATION_ROUND_COMPLETED`, `CONSENSUS_REACHED` |
| Council | `COUNCIL_STARTED`, `COUNCIL_DECISION`, `COUNCIL_COMPLETED` |
| System | `ERROR`, `MODE_TRANSITION` |

---

## 10. TUI LAYER

**File:** `src/rilai/tui/app.py` (913 lines)

### Key Classes

| Class | Purpose |
|-------|---------|
| `RilaiTUI` | Main Textual application |
| `RealEngine` | Adapter bridging core Engine to TUI |
| `MockEngine` | Demo engine for testing |
| `EngineEvent` | Event data structure for TUI streaming |

### TUI Event Flow

```
User types message
    ↓
Input.Submitted event
    ↓
_send_user_text() → run_worker(_run_turn())
    ↓
_run_turn() async generator consumer:
  1. Sets activity to "SENSING"
  2. Calls engine.stream_turn(user_text) - ASYNC GENERATOR
  3. For each EngineEvent yielded:
     → _apply_event(event)
  4. Sets activity to "IDLE"
    ↓
_apply_event() routes event.kind to panel update:
  - "sensors" → updates #sensors-table
  - "stance" → updates #stance-table + status strip
  - "agent_log" → writes to #agent-log
  - "workspace" → updates #workspace-pretty
  - "critics" → clears/repopulates #critics-table
  - "memory" → writes to #memory-log
  - "assistant" → writes to #chat-log
  - "activity" → updates #activity-bar
```

### Inspector Tabs

| Tab | Widget | Content |
|-----|--------|---------|
| Sensors | DataTable | sensor, probability, evidence |
| Stance | DataTable | 8 dimension metrics + values |
| Agents | RichLog | Agent voices/glimpses during processing |
| Workspace | Pretty | Goal, primary_question, constraints |
| Critics | DataTable | Validation results |
| Memory | RichLog | Conversation summary + hypotheses |

---

## 11. OPENROUTER PROVIDER

**File:** `src/rilai/providers/openrouter.py`

### Thinking Model Support

Automatically detects and extracts reasoning from:
- DeepSeek R1 family
- Claude `:thinking` variants
- OpenAI o1/o3
- Gemini 2.5
- Qwen QwQ

### Model Response

```python
@dataclass
class ModelResponse:
    content: str              # Main response
    reasoning: str | None     # Thinking steps (if thinking model)
    model: str
    finish_reason: str
    usage: TokenUsage         # prompt, completion, reasoning tokens
    latency_ms: int
    reasoning_effort: str | None  # "minimal", "low", "medium", "high"
```

### Configuration

```python
MODELS = {
    "small": "meta-llama/llama-3.1-8b-instruct",
    "medium": "meta-llama/llama-3.3-70b-instruct",
    "large": "deepseek/deepseek-chat",
}

REASONING_EFFORT = {
    "agent_assess": "minimal",        # ~500 tokens
    "deliberation": "medium",         # ~5000 tokens
    "council_synthesis": "high",      # ~10000 tokens
}
```

---

## 12. KEY FILE REFERENCE

| File | Purpose |
|------|---------|
| `src/rilai/cli.py` | CLI entry point (`rilai`, `rilai shell`) |
| `src/rilai/tui/app.py` | Main TUI application |
| `src/rilai/core/engine.py` | Main processing orchestrator |
| `src/rilai/core/events.py` | Event bus infrastructure |
| `src/rilai/core/turn_state.py` | TurnState and EngineResult |
| `src/rilai/core/stance.py` | StanceVector dataclass |
| `src/rilai/core/stance_aggregator.py` | Aggregate stance from agents |
| `src/rilai/core/sensor_extractor.py` | Fast deterministic sensors |
| `src/rilai/core/workspace_aggregator.py` | Build workspace summary |
| `src/rilai/core/memory_extractor.py` | Extract memory summary |
| `src/rilai/core/critics_integration.py` | Run validation critics |
| `src/rilai/agencies/runner.py` | Parallel agency execution |
| `src/rilai/agencies/base.py` | GenericAgency base class |
| `src/rilai/agencies/registry.py` | All 10 agencies configuration |
| `src/rilai/council/pipeline.py` | Council orchestrator |
| `src/rilai/council/deliberation.py` | Multi-round deliberation |
| `src/rilai/council/synthesizer.py` | LLM-based synthesis |
| `src/rilai/council/voice.py` | Voice rendering |
| `src/rilai/sensors/runner.py` | Sensor ensemble execution |
| `src/rilai/sensors/schema.py` | Sensor data structures |
| `src/rilai/brain/modulators.py` | GlobalModulators, AgentActivationState |
| `src/rilai/providers/openrouter.py` | LLM provider with thinking support |
| `src/rilai/memory/database.py` | SQLite database layer |
| `src/rilai/memory/short_term.py` | JSON temporary storage |
| `src/rilai/observability/store.py` | Unified dual-write store |
| `src/rilai/config/defaults.py` | Built-in configuration defaults |
| `src/rilai/config/loader.py` | Configuration loading |
| `config.py` | User configuration (gitignored) |

---

## 13. KNOWN ISSUES: WHY TUI PANELS DON'T UPDATE

Based on code review, here's the precise diagnosis:

### The Event Flow IS Set Up Correctly

After verifying the code, the event infrastructure IS properly wired:

1. **runner.py:104-192** - `run_all_traced()` DOES emit events:
   - `AGENCY_STARTED` for each agency (line 124-126)
   - `AGENT_STARTED` for each agent (line 210-212)
   - `AGENT_COMPLETED` with thinking + voice (line 228-237)
   - `AGENCY_COMPLETED` after each agency (line 137-147)

2. **app.py:155-179** - `RealEngine` DOES subscribe to events:
   - Subscribes in `_subscribe_to_events()` called from `start()`
   - `_on_agent_completed()` queues EngineEvent to `_event_queue`

3. **app.py:207-266** - `stream_turn()` DOES yield events:
   - Creates task for `process_message()`
   - Polls `_event_queue` with 0.1s timeout while task runs
   - Yields final state from `turn_state` after task completes

### The Root Cause: Async Event Handler Timing

The issue is subtle. In `stream_turn()`:

```python
task = asyncio.create_task(self._engine.process_message(user_text))  # Line 220
while not task.done():
    try:
        event = await asyncio.wait_for(self._event_queue.get(), timeout=0.1)  # Line 225
        yield event
    except asyncio.TimeoutError:
        continue
```

**Problem:** The event handlers `_on_agent_completed()` etc. are async functions that call `await self._event_queue.put(...)`. But:
- `event_bus.emit()` calls handlers with `asyncio.gather()`
- The handlers ARE being called, BUT...
- The `await self._event_queue.put()` in handlers is happening on a DIFFERENT task context
- The 0.1s polling loop may miss events entirely if the task completes before events queue

### Issue 2: Events Yield AFTER Processing Completes

Looking at lines 233-266, the final state (sensors, stance, workspace, agents, critics, memory, assistant) is ONLY yielded AFTER `task = await task` completes. This means:
- Real-time streaming during processing → few events (agent_log only)
- Final state → all events at once, at the end

The TUI panels DO update, but only at the END of processing, not during.

### Issue 3: Limited Real-Time Events

`RealEngine` only subscribes to 5 event types:
- `AGENT_COMPLETED` → agent_log
- `AGENCY_STARTED` → activity "SENSING"
- `COUNCIL_STARTED` → activity "THINKING"
- `COUNCIL_DECISION` → workspace (partial)
- `ERROR` → activity "ALERT"

Missing subscriptions:
- `DELIBERATION_ROUND_STARTED` / `DELIBERATION_ROUND_COMPLETED`
- `CONSENSUS_REACHED`
- `PROCESSING_COMPLETED` with full stats

### Issue 4: Sensors/Stance/Critics Only From Final State

These panels are ONLY updated from `turn_state` AFTER processing:
- `sensors` - extracted from event, not streamed
- `stance` - aggregated from collected assessments
- `critics` - run after response generated

They CANNOT update in real-time with current architecture.

---

## 14. WHAT EXISTS VS WHAT'S MISSING

### Fully Implemented

- [x] Core engine with process_message()
- [x] 10 agencies with 49+ agents
- [x] Agency gating logic
- [x] Multi-round deliberation
- [x] Council synthesis and voice rendering
- [x] SQLite + JSON dual storage
- [x] Event bus infrastructure
- [x] OpenRouter provider with thinking support
- [x] TUI with 6 inspector tabs
- [x] Stance aggregation
- [x] Fast sensor extraction

### Partially Implemented / Needs Work

- [ ] Real-time TUI updates (events not flowing to panels)
- [ ] Full sensor ensemble (runner exists but may not be called)
- [ ] Modulator updates from agent outputs (map exists, inference unclear)
- [ ] AgentActivationState cooldown (data structure exists, usage unclear)
- [ ] Critics validation (integration exists, critic definitions unclear)
- [ ] Memory extraction (may be stubbed)

### Not Yet Implemented

- [ ] Brain daemon (background tick loop)
- [ ] Proactive suggestions/nudges
- [ ] Episode building
- [ ] Long-term memory retrieval
- [ ] User baseline modeling

---

## 15. RECOMMENDED REFACTORING PRIORITIES

1. **Fix TUI Event Streaming** - Ensure events flow from engine to panels
2. **Add Logging/Tracing** - Instrument key paths to understand data flow
3. **Simplify Event Flow** - Consider direct callbacks vs event bus for TUI
4. **Test Agent Pipeline** - Unit tests for individual agents
5. **Document Agent Prompts** - Ensure all 49+ agent prompts exist in `prompts/`
6. **Clean Up Unused Code** - Remove stubs and placeholder implementations
7. **Add Error Handling** - Graceful degradation when agents fail

---

## 16. APPENDIX: PROMPT FILE LOCATIONS

Agent prompts are expected at:
```
src/rilai/prompts/
├── agents/
│   ├── {agency_name}/
│   │   └── {agent_name}.md
│   └── ...
├── council/
│   ├── synthesizer.md
│   └── voice.md
└── sensors/
    └── {sensor_name}.md
```

---

## 17. EXECUTIVE SUMMARY FOR REVIEWER

### What Rilai v2 IS

A cognitive architecture for AI companionship using a "Society of Mind" approach:
- **49+ specialized agents** organized into **10 agencies**
- **Multi-round deliberation** where agents hear each other and adjust positions
- **Council synthesis** that decides what to say and how to say it
- **Textual TUI** with real-time telemetry display
- **Dual storage** (SQLite permanent + JSON ephemeral)
- **OpenRouter provider** with native thinking model support

### What Works

- Core engine processing pipeline
- Agency parallel execution with gating
- Council deliberation and voice rendering
- Storage and tracing
- Event bus infrastructure
- TUI layout and widget composition
- Final state rendering to panels

### What Doesn't Work

- **Real-time panel updates during processing** - Events flow correctly but TUI only updates at END
- **Streaming telemetry** - Only agent_log streams; sensors/stance/critics batch at end

### Architecture Strengths

- Clean separation: Engine → Events → TUI adapter → Widgets
- Async-first design throughout
- Comprehensive tracing and observability
- Well-defined data contracts (EngineEvent, TurnState)

### Technical Debt / Cleanup Candidates

1. **Event bus timing** - Consider direct callbacks for TUI instead of async queue
2. **RealEngine coupling** - Subscribes to some events but misses others
3. **Duplicate event emissions** - Both engine.py and runner.py emit PROCESSING_STARTED
4. **Unused imports/code** - Episode builder only used in /play, not main chat
5. **Error handling** - Silent failures in _apply_event()
6. **Missing tests** - No test coverage for TUI streaming

### Code Line Counts (Approximate)

| Component | Lines | Files |
|-----------|-------|-------|
| TUI | ~900 | 1 |
| Engine | ~280 | 1 |
| Agencies | ~600 | 3 |
| Council | ~800 | 5 |
| Sensors | ~400 | 3 |
| Events | ~300 | 1 |
| Storage | ~700 | 3 |
| Providers | ~300 | 1 |
| **Total Core** | **~4,300** | **18** |

---

*Verified against source files: engine.py, app.py, runner.py*

---

*End of Document*
