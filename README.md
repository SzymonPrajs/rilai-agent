# Rilai v2

**Cognitive architecture for AI companionship** — a Society of Mind implementation with multi-agent deliberation, event-sourced state, and Textual TUI.

Named after Riley from *Inside Out*, who had a council of emotions in her head. Rilai implements the same concept: multiple specialized agents evaluate each interaction, then a council synthesizes their perspectives into a unified response.

## Quick Start

```bash
# Copy config and add your OpenRouter API key
cp config.example.py config.py
# Edit config.py with your API key

# Install
pip install -e .

# Run TUI
rilai

# Run shell (no TUI)
rilai shell
```

## Architecture Overview

Rilai processes each user message through an **8-stage pipeline**, using a **workspace** (global blackboard) that agents read from and propose updates to. The system is fully **event-sourced** — every operation emits immutable events persisted to SQLite.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INPUT                                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Stage 0: INGEST          │  Store message, increment turn_id               │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 1: FAST SENSORS    │  Regex-based detection (no LLM)                 │
│                           │  → vulnerability, advice_requested, safety_risk │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 2: MEMORY          │  Retrieve episodes, user facts, open threads    │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 3-4: AGENT WAVES   │  Wave 0: Always-on agents (censor, trigger)     │
│                           │  Wave 1+: Scheduled agents based on sensors     │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 5: DELIBERATION    │  Build argument graph from claims               │
│                           │  Multi-round consensus (exit at 0.9+)           │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 6: COUNCIL + VOICE │  Council: decide whether/how to speak           │
│                           │  Voice: render decision to natural language     │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 7: CRITICS         │  Validate response (no premature advice, etc)   │
├───────────────────────────┼─────────────────────────────────────────────────┤
│  Stage 8: MEMORY COMMIT   │  Persist turn, update user model                │
└───────────────────────────┴─────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              RESPONSE                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose | Location |
|-----------|---------|----------|
| **TurnRunner** | Orchestrates the 8-stage pipeline | `runtime/turn_runner.py` |
| **Workspace** | Global mutable state (blackboard pattern) | `runtime/workspace.py` |
| **Scheduler** | Decides which agents run per wave | `runtime/scheduler.py` |
| **Reducer** | Merges agent proposals into workspace | `runtime/reducer.py` |
| **Deliberation** | Builds argument graph, computes consensus | `runtime/deliberation.py` |
| **Council** | Decides whether/how to respond | `runtime/council.py` |
| **Voice** | Renders council decision to text | `runtime/voice.py` |

## Workspace (Global Blackboard)

The workspace is the system's working memory — a mutable state that all agents read from and propose updates to. Agents don't modify it directly; they propose changes through their outputs, which the **Reducer** merges deterministically.

### Workspace Contents

```python
user_message: str              # Current input
turn_id: int                   # Logical turn counter
conversation_history: list     # Chat log
retrieved_episodes: list       # Episodic memories
user_facts: list               # Learned facts about user
open_threads: list             # Active topics/goals
stance: StanceVector           # Global affective modulation (8D)
modulators: GlobalModulators   # Control parameters
active_claims: list[Claim]     # Claims from deliberation
sensors: dict                  # Environment sensor readings
```

### Stance Vector (8 Dimensions)

Based on the PAD (Pleasure-Arousal-Dominance) model extended with cognitive-social dimensions:

```python
# Core affective (PAD model)
valence: float [-1, 1]     # unpleasant ← → pleasant
arousal: float [0, 1]      # calm ← → activated
control: float [0, 1]      # helpless ← → dominant

# Cognitive-social modulators
certainty: float [0, 1]    # confused ← → clear
safety: float [0, 1]       # threatened ← → secure
closeness: float [0, 1]    # distant ← → connected
curiosity: float [0, 1]    # saturated ← → wondering
strain: float [0, 1]       # ease ← → overload
```

The stance vector modulates response generation (readiness_to_speak, advice_suppression, warmth_level). Agents propose `stance_delta` changes, which the Reducer applies with leaky integration (alpha=0.25, max delta=±0.15).

## Agent System

Rilai implements a **Society of Mind** architecture with **10 agencies** containing **49 agents**. Each agency advocates for a specific value (safety, connection, understanding, etc.) and contains specialized sub-agents.

### Agency Hierarchy

| Domain | Agency | Agents | Value | Always Active |
|--------|--------|--------|-------|---------------|
| Goal-Oriented | **PLANNING** | difference_engine, short_term, long_term, priority | PRODUCTIVITY | No |
| Goal-Oriented | **RESOURCE** | financial, time, energy | RESOURCES | No |
| Goal-Oriented | **SELF** | identity, values, meta_monitor, attachment_learner, reflection, self_model | IDENTITY | Yes |
| Evaluative | **EMOTION** | wellbeing, **stress**\*, motivation, mood_regulator, wanting | WELLBEING | No |
| Evaluative | **SOCIAL** | relationships, empathy, norms, attachment_detector, mental_model | CONNECTION | No |
| Problem-Solving | **REASONING** | debugger, researcher, reformulator, analogizer, creative, magnitude | UNDERSTANDING | No |
| Problem-Solving | **CREATIVE** | brainstormer, synthesizer, frame_builder | CREATIVITY | No |
| Control | **INHIBITION** | **censor**\*, suppressor, **exception_handler**\* | SAFETY | Yes |
| Control | **MONITORING** | **trigger_watcher**\*, **anomaly_detector**\*, interrupt_manager, attention | AWARENESS | Yes |
| Action | **EXECUTION** | executor, habits, script_runner, context_manager, output_filter | ACTION | No |

\* **Always-on agents** — run every turn regardless of sensors

### Agent Output Structure

Each agent returns structured output that feeds into deliberation:

```python
@dataclass
class AgentOutput:
    observation: str           # What I noticed (1-3 sentences)
    salience: float            # urgency × confidence [0, 1]
    urgency: int               # 0=background, 1=routine, 2=important, 3=must act now
    confidence: int            # 0=uncertain, 1=plausible, 2=likely, 3=certain
    claims: list[Claim]        # Atomic propositions for deliberation
    stance_delta: dict         # Proposed modulation changes
    workspace_patch: dict      # Proposed workspace field updates
    memory_candidates: list    # Things worth remembering
    debug_trace: str           # Reasoning (stored, not always displayed)
```

### Agent Scheduling

1. **Wave 0**: Always-on agents run every turn (censor, stress, exception_handler, trigger_watcher, anomaly_detector)
2. **Wave 1+**: Scheduled agents based on:
   - Sensor activations (domain markers in user message)
   - Modulator state (emotional depth, proactivity)
   - Token budget constraints
   - Cooldown filtering (prevent agent spam)

## Claim-Based Deliberation

Agents communicate through **claims** — atomic propositions that form an argument graph. This enables multi-round deliberation where agents can hear each other and adjust positions.

### Claim Structure

```python
@dataclass
class Claim:
    id: UUID
    text: str                  # Atomic statement (max 200 chars)
    type: ClaimType            # OBSERVATION, RECOMMENDATION, CONCERN, QUESTION
    source_agent: str          # Which agent made it
    urgency: int               # 0-3 scale
    confidence: int            # 0-3 scale
    supports: list[UUID]       # Claims this supports
    opposes: list[UUID]        # Claims this opposes
```

### Deliberation Rounds

1. **Round 0**: Process initial agent outputs, extract claims, build argument graph
2. **Round N**: If consensus < threshold, request focused follow-ups from contested agents
3. **Exit Conditions**:
   - Consensus ≥ 0.9 (high agreement)
   - Max 3 rounds reached
   - Early exit at 0.7+ if no contested claims remain

Consensus is computed from claim urgency, confidence, and the support/oppose graph topology.

## Council & Voice

The final response is generated in two steps: **Council** decides *what* to say, **Voice** renders *how* to say it.

### Council Decision

The council analyzes the argument graph and determines:

```python
@dataclass
class CouncilDecision:
    should_speak: bool         # YES or NO
    urgency: str               # low | medium | high | critical
    speech_act: SpeechAct      # What/how to say it
```

### Speech Act

```python
@dataclass
class SpeechAct:
    intent: str                # witness, guide, clarify, protect, celebrate, observe
    key_points: list[str]      # Main content bullets
    tone: str                  # warm, concerned, playful, serious, etc.
    do_not: list[str]          # Things to avoid
    asks_user: list[str]       # Questions to pose
```

### Voice Rendering

Voice takes the `CouncilDecision` + workspace context and generates natural language:

```python
@dataclass
class VoiceResult:
    text: str                  # Rendered response
    rendered: bool             # Success flag
    token_count: int           # Tokens used
    speech_act: SpeechAct      # What was followed
    reasoning: str             # From thinking models (if available)
```

Special cases:
- **Safety interrupt** → protective care response
- **Silent turn** → no response needed (council decides not to speak)
- **High dispute** → escalate to larger model

## Event Sourcing

Every operation in Rilai emits immutable `EngineEvent` objects, enabling replay, debugging, and analysis.

### Event Structure

```python
@dataclass
class EngineEvent:
    session_id: str
    turn_id: int
    seq: int                   # Sequence within turn
    ts_monotonic: float        # Timing
    kind: EventKind            # 40+ event types
    payload: dict              # Event-specific data
```

### Event Categories

| Category | Event Types |
|----------|-------------|
| Turn Lifecycle | TURN_STARTED, TURN_STAGE_CHANGED, TURN_COMPLETED |
| Sensors | SENSORS_FAST_UPDATED, SENSORS_ENSEMBLE_UPDATED |
| Agents | AGENT_STARTED, AGENT_COMPLETED, AGENT_FAILED, WAVE_STARTED, WAVE_COMPLETED |
| Workspace | WORKSPACE_PATCHED, STANCE_UPDATED, MODULATORS_UPDATED |
| Deliberation | DELIB_ROUND_STARTED, DELIB_ROUND_COMPLETED, CONSENSUS_UPDATED |
| Council+Voice | COUNCIL_DECISION_MADE, VOICE_RENDERED |
| Critics | CRITICS_UPDATED, SAFETY_INTERRUPT |
| Memory | MEMORY_RETRIEVED, MEMORY_CANDIDATES_PROPOSED, MEMORY_COMMITTED |

All events are persisted to SQLite (`store/event_log.py`).

## Complete Data Flow Example

```
User: "I'm feeling anxious about the meeting tomorrow"
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 0: INGEST                                                   │
│   → Store message, turn_id = 42                                   │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 1: FAST SENSORS (regex, no LLM)                             │
│   → vulnerability = 0.8                                           │
│   → relational_bid = 0.4                                          │
│   → advice_requested = false                                      │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 2: MEMORY RETRIEVAL                                         │
│   → Past meeting notes                                            │
│   → User's anxiety patterns                                       │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 3-4: AGENT WAVES                                            │
│                                                                   │
│ Wave 0 (Always-On):                                               │
│   censor          → "No safety concerns"                          │
│   trigger_watcher → "Anxiety pattern detected" [U:2 C:3]          │
│                                                                   │
│ Wave 1 (Scheduled by sensors):                                    │
│   emotion.stress        → Claim: "High stress about future event" │
│                           [U:2 C:2]                               │
│   social.relationships  → Claim: "Social stakes feel high"        │
│                           [U:1 C:2]                               │
│   planning.short_term   → Claim: "User needs concrete next steps" │
│                           [U:2 C:1]                               │
│   reasoning.debugger    → Claim: "Anxiety is protective signal"   │
│                           [U:1 C:3]                               │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 5: DELIBERATION                                             │
│                                                                   │
│ Round 0:                                                          │
│   → Build argument graph from 4 claims                            │
│   → stress.claim supports planning.claim                          │
│   → debugger.claim reframes stress.claim                          │
│   → Consensus: 0.75 (not locked)                                  │
│                                                                   │
│ Round 1:                                                          │
│   → Request follow-up: reasoning.reformulator                     │
│   → New claim: "Reframe anxiety as readiness signal"              │
│   → Consensus: 0.88 (exit threshold met)                          │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 6: COUNCIL + VOICE                                          │
│                                                                   │
│ Council Decision:                                                 │
│   should_speak: true                                              │
│   urgency: MEDIUM                                                 │
│   speech_act:                                                     │
│     intent: "guide"                                               │
│     key_points: ["acknowledge anxiety", "reframe as readiness"]   │
│     tone: "warm, grounded"                                        │
│     do_not: ["dismiss", "give unsolicited advice"]                │
│     asks_user: ["What's the meeting about?"]                      │
│                                                                   │
│ Voice Rendering:                                                  │
│   "I notice you're preparing for something important tomorrow.    │
│    That anxiety makes sense — it means you care about how it      │
│    goes. What's the meeting about? Sometimes getting specific     │
│    helps."                                                        │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 7: CRITICS                                                  │
│   → Premature advice check: PASS (invitation, not advice)         │
│   → Truthfulness check: PASS (no false claims)                    │
│   → Calibration check: PASS (warmth appropriate to vulnerability) │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
┌───────────────────────────────────────────────────────────────────┐
│ Stage 8: MEMORY COMMIT                                            │
│   → Store turn in episode log                                     │
│   → Update user model: anxiety_pattern++                          │
│   → Persist 12 EngineEvents to SQLite                             │
└───────────────────────────────────────────────────────────────────┘
    │
    ▼
Response displayed to user
```

## CLI Commands

```bash
rilai                     # Launch TUI (default)
rilai shell               # Interactive REPL without TUI
rilai clear current       # Clear current session
rilai clear sessions      # Clear all sessions
rilai clear all           # Clear everything
rilai status              # Show system status
rilai query agent-calls   # Query agent execution logs
rilai query stats         # Show statistics
rilai synthetic <scene>   # Run synthetic test scenarios
```

### TUI Interface

```
┌─────────────────────────────────┬───────────────────────────────┐
│         Chat Panel              │       Status Panels           │
│                                 │  - Agency activity            │
│  User: I'm feeling anxious...   │  - Stance vector              │
│  Rilai: I notice you're...      │  - Active claims              │
│                                 │  - Agent thinking traces      │
└─────────────────────────────────┴───────────────────────────────┘
  > Input with /slash commands                       [Ctrl+D quit]
```

## Configuration

Edit `config.py` (copy from `config.example.py`):

```python
OPENROUTER_API_KEY = "sk-or-v1-..."

# Model tiers for different tasks
MODELS = {
    "small": "meta-llama/llama-3.1-8b-instruct",    # Fast sensors, simple agents
    "medium": "meta-llama/llama-3.3-70b-instruct",  # Most agent calls
    "large": "deepseek/deepseek-chat",              # Council, voice, escalation
}

# Thinking models are supported natively
# Reasoning extracted from message.reasoning or <think> tags
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/
```

### Key Source Files

| File | Purpose |
|------|---------|
| `src/rilai/cli.py` | CLI entry point |
| `src/rilai/runtime/turn_runner.py` | Main 8-stage orchestration |
| `src/rilai/runtime/workspace.py` | Global state management |
| `src/rilai/runtime/scheduler.py` | Agent wave scheduling |
| `src/rilai/runtime/reducer.py` | Deterministic state merging |
| `src/rilai/runtime/deliberation.py` | Argument graph & consensus |
| `src/rilai/runtime/council.py` | Response decision making |
| `src/rilai/runtime/voice.py` | Natural language rendering |
| `src/rilai/contracts/` | All data models (Pydantic/dataclass) |
| `src/rilai/prompts/agents/` | 49 agent prompts organized by agency |
| `src/rilai/store/event_log.py` | SQLite event persistence |

## Design Principles

1. **Event-Sourced**: Every operation is immutable and replay-able
2. **Deterministic Merging**: Reducer is a pure function for predictable state evolution
3. **Multi-Perspective**: Agents represent different cognitive concerns, not just task-solvers
4. **Claim-Based Reasoning**: Arguments are first-class objects that can support/oppose each other
5. **Soft Constraints**: Stance bounds + max delta prevent instability
6. **Safety First**: Always-on censors + early-exit on high safety_risk
7. **Thinking Model Native**: Automatic reasoning token extraction from compatible models

## License

MIT
