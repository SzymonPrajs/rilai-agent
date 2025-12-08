# Document 12: Wire Up Agent Pipeline (Remove Stubs)

**Purpose:** Connect stub implementations in `stages.py` to real agent, council, and voice modules
**Execution:** One Claude Code session
**Dependencies:** 01-contracts, 02-event-store, 03-runtime-core, 04-workspace, 05-agents (partial), 07-council-voice
**Status:** ✅ COMPLETE

---

## Implementation Checklist

> **Instructions:** Mark items with `[x]` when complete. After completing items here,
> also update the master checklist in `00-overview.md`.

### Provider Updates
- [x] Add `generate(tier=...)` method to `OpenRouterClient`
- [x] Add `get_provider()` helper function
- [x] Fix Voice model reference to use tier lookup
- [x] Fix Voice `TokenUsage` access (`.total_tokens` not `.get()`)

### Stage Implementations
- [x] Replace `run_agent_waves()` stub with real `MicroAgentRunner` calls
- [x] Replace `run_council()` stub with real `Council` + `Voice` calls
- [x] Replace `run_critics()` stub with real `Critics` validation
- [x] Handle scheduler placeholder IDs gracefully (fall back to triggered agents)

### Workspace Updates
- [x] Verify `sensors` attribute exists
- [x] Verify `active_claims` attribute exists
- [x] Add `active_claims` setter property
- [x] Add transient storage attributes (`_agent_outputs`, `_active_claims`)

### ElevenLabs Scribe STT (Bonus)
- [x] Add config placeholders in `config.example.py`
- [x] Create `providers/elevenlabs_stt.py` with `ScribeRealtimeClient`
- [x] WebSocket-based streaming transcription
- [x] VAD (Voice Activity Detection) support
- [x] Word-level timestamps

### TUI Integration
- [x] Activity panel shows real stage progression
- [x] Sensors panel updates from fast sensors
- [x] Agents panel shows agent completions
- [x] Critics panel shows validation results

### CLI Integration
- [x] `rilai shell` processes messages through real pipeline
- [x] `rilai` TUI updates panels in real-time

### Verification
- [x] Response is NOT "I hear you. You said: ..."
- [x] Processing takes ~15 seconds with real LLM calls
- [x] End-to-end test passes

### Notes

**Test Results (2024-12-08):**
```
=== Test 1: Simple greeting ===
Completed in 15928ms
PASS: Real response received
```

**Known Behaviors:**
- Some agents fail JSON parsing with certain models (handled gracefully with salience=0)
- Response time depends on model tier and OpenRouter queue

---

## Problem Summary (RESOLVED)

The entire Rilai agent processing pipeline was **stubbed out** in `src/rilai/runtime/stages.py`. When a user sent a message:

1. Fast sensors run (working) ✓
2. Memory retrieval stub → returns empty lists (still stub)
3. ~~Agent waves stub → returns `"observation": "Quiet"`, `salience: 0.0`~~ → NOW RUNS REAL AGENTS
4. Deliberation stub → returns fake 95% consensus (still stub)
5. ~~Council stub → returns hardcoded `"I hear you. You said: {message}"`~~ → NOW CALLS REAL COUNCIL
6. ~~Critics stub → all pass~~ → NOW RUNS REAL CRITICS
7. Memory commit stub → does nothing (still stub)

**The placeholder response at `stages.py:233` is NO LONGER RETURNED.**

---

## Files Modified

| File | Changes |
|------|---------|
| `src/rilai/providers/openrouter.py` | Added `generate(tier=...)` method, `get_provider()` function |
| `src/rilai/providers/elevenlabs_stt.py` | **NEW** - ElevenLabs Scribe realtime STT client |
| `src/rilai/providers/__init__.py` | Exports for new functions and STT client |
| `src/rilai/runtime/stages.py` | Replaced stubs for `run_agent_waves()`, `run_council()`, `run_critics()` |
| `src/rilai/runtime/voice.py` | Fixed model lookup, fixed `TokenUsage` access |
| `src/rilai/runtime/workspace.py` | Added `active_claims` setter |
| `config.example.py` | Added ElevenLabs STT config, updated model tiers |

---

## Implementation Details

### Step 1: Add `generate()` to OpenRouterClient ✅

**File:** `src/rilai/providers/openrouter.py:290-319`

```python
async def generate(
    self,
    messages: list[dict],
    tier: str = "small",
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> ModelResponse:
    """Generate completion using tier-based model selection."""
    config = get_config()
    model = config.MODELS.get(tier, config.MODELS.get("small"))
    msg_objects = [Message(role=m["role"], content=m["content"]) for m in messages]
    return await self.complete(
        messages=msg_objects,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_provider() -> OpenRouterClient:
    """Get the singleton OpenRouter client."""
    return openrouter
```

---

### Step 2: Fix Voice Model Reference ✅

**File:** `src/rilai/runtime/voice.py:61-76`

```python
# Get model from config
from rilai.config import get_config
from rilai.providers.openrouter import Message
config = get_config()
model = config.MODELS.get("medium", config.MODELS.get("small"))

response = await provider.complete(
    messages=[
        Message(role="system", content=self._get_system_prompt()),
        Message(role="user", content=prompt),
    ],
    model=model,
)

text = response.content.strip()
token_count = response.usage.total_tokens if response.usage else 0
```

---

### Step 3: Replace `run_agent_waves()` Stub ✅

**File:** `src/rilai/runtime/stages.py:132-250`

Key changes:
- Imports `MicroAgentRunner` and `openrouter`
- Converts workspace stance to `core.stance.StanceVector` (dataclass)
- Validates agent IDs against catalog, falls back to triggered agents
- Calls `agent_runner.run()` with real LLM calls
- Emits `AGENT_STARTED`/`AGENT_COMPLETED` events
- Merges stance deltas from agents
- Converts high-salience outputs to `Claim` objects for council

---

### Step 4: Replace `run_council()` Stub ✅

**File:** `src/rilai/runtime/stages.py:288-323`

Key changes:
- Imports `Council` and `Voice`
- Populates `workspace.active_claims` from agent outputs
- Calls `council.decide(workspace)` for decision
- Calls `voice.render(decision, workspace)` for natural language generation
- Sets `workspace.current_goal` and `workspace.constraints`

---

### Step 5: Replace `run_critics()` Stub ✅

**File:** `src/rilai/runtime/stages.py:357-389`

Key changes:
- Imports `Critics`
- Reconstructs minimal `CouncilDecision` for critics
- Calls `critics.validate()` which runs safety, coherence, tone, and length checks

---

### Step 6: ElevenLabs Scribe STT ✅ (Bonus)

**File:** `src/rilai/providers/elevenlabs_stt.py`

Features:
- `ScribeRealtimeClient` class with WebSocket connection
- VAD (Voice Activity Detection) for automatic segmentation
- Word-level timestamps
- Partial and committed transcript events
- Exponential backoff reconnection

**Config:** `config.example.py:78-101`

```python
ELEVENLABS_STT_MODEL = "scribe_v2_realtime"
ELEVENLABS_STT_LANGUAGE = "en"
ELEVENLABS_STT_COMMIT_STRATEGY = "vad"
ELEVENLABS_STT_VAD_THRESHOLD = 0.4
ELEVENLABS_STT_VAD_SILENCE_SECS = 1.5
ELEVENLABS_STT_INCLUDE_TIMESTAMPS = True
```

---

## Data Flow After Implementation

```
User Message
    ↓
Stage 1: Fast Sensors → sensors dict
    ↓
Stage 2: Memory Retrieval (stub) → empty lists
    ↓
Stage 3-4: run_agent_waves()
    → MicroAgentRunner.run()
    → openrouter.generate(tier="tiny")
    → LLM calls via OpenRouter API
    → MicroAgentOutput with salience, hypotheses, glimpses
    → Convert to Claims for council
    ↓
Stage 5: run_deliberation() (stub) → 95% consensus
    ↓
Stage 6: run_council()
    → Council.decide() → CouncilDecision (speak, urgency, speech_act)
    → Voice.render()
    → openrouter.complete(model=MODELS["medium"])
    → Natural language response
    ↓
Stage 7: run_critics()
    → Critics.validate()
    → Safety/coherence/tone/length checks
    ↓
Stage 8: Memory Commit (stub) → no-op
    ↓
Response returned (REAL RESPONSE, not stub)
```

---

## Remaining Stubs (Future Work)

| Stage | Status | Future Document |
|-------|--------|-----------------|
| Memory Retrieval | Stub | 08-memory |
| Deliberation | Stub | 06-deliberation |
| Memory Commit | Stub | 08-memory |

---

## Dependencies

- `config.py` must have valid `OPENROUTER_API_KEY`
- `config.py` must have valid `MODELS` dict with tiers:
  ```python
  MODELS = {
      "tiny": "openai/gpt-oss-20b",
      "small": "openai/gpt-oss-120b",
      "medium": "x-ai/grok-4.1-fast",
      "large": "google/gemini-3-pro-preview",
  }
  ```
- For ElevenLabs STT: `ELEVENLABS_API_KEY` required
