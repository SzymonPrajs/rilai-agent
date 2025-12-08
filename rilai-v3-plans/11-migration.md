# Document 11: Migration Checklist

**Purpose:** Complete migration from v2 to v3, file deletions, and cleanup
**Execution:** One Claude Code session (final)
**Dependencies:** All previous documents (00-10)

---

## Implementation Checklist

> **Instructions:** Mark items with `[x]` when complete. After completing items here,
> also update the master checklist in `00-overview.md`.

### Pre-Migration
- [ ] Create `v2-archive` branch
- [ ] Push archive branch to origin
- [ ] Create `v3-migration` branch

### Database Migration
- [ ] Create events.db with schema
- [ ] Create memory.db with schema
- [ ] Run migration script (if data to preserve)

### Agent Prompts (49 total)
- [ ] Emotion agents (5): stress, wellbeing, motivation, mood_regulator, wanting
- [ ] Social agents (5): relationships, empathy, norms, attachment_detector, mental_model
- [ ] Planning agents (4): difference_engine, short_term, long_term, priority
- [ ] Resource agents (3): financial, time, energy
- [ ] Self agents (6): identity, values, meta_monitor, attachment_learner, reflection, self_model
- [ ] Reasoning agents (6): debugger, researcher, reformulator, analogizer, creative, magnitude
- [ ] Creative agents (3): brainstormer, synthesizer, frame_builder
- [ ] Inhibition agents (3): censor, suppressor, exception_handler
- [ ] Monitoring agents (4): trigger_watcher, anomaly_detector, interrupt_manager, attention
- [ ] Execution agents (6): executor, habits, script_runner, context_manager, output_filter, general_responder

### File Cleanup
- [ ] Delete `src/rilai/core/` folder
- [ ] Delete `src/rilai/agencies/` folder
- [ ] Delete `src/rilai/council/` folder
- [ ] Delete `src/rilai/brain/` folder
- [ ] Delete old `src/rilai/tui/` folder
- [ ] Delete `src/rilai/agents/protocol.py`
- [ ] Delete `src/rilai/memory/database.py`
- [ ] Delete `src/rilai/memory/short_term.py`
- [ ] Delete `src/rilai/observability/store.py`
- [ ] Delete `src/rilai/sensors/runner.py`
- [ ] Delete `data/current/` folder

### Update Files
- [ ] Update `pyproject.toml` version to 3.0.0
- [ ] Update any remaining imports

### Final Verification
- [ ] `rilai` starts TUI with streaming updates
- [ ] `rilai shell` works with event-sourced pipeline
- [ ] All panels update in real-time
- [ ] Event log is replayable
- [ ] Background daemon emits proactive nudges
- [ ] Memory retrieval injects context
- [ ] All agents output structured JSON
- [ ] No dual-write - single SQLite event log
- [ ] All unit tests pass
- [ ] Integration tests pass

### Git Cleanup
- [ ] Commit all changes
- [ ] Merge to main (after testing)
- [ ] Tag `v3.0.0`
- [ ] Push tags

### Notes
_Add any implementation notes, issues, or decisions here:_

---

## Overview

This document provides the complete migration checklist for transitioning from Rilai v2 to v3. It covers:
1. Files to delete
2. Files to keep and modify
3. New directory structure
4. Data migration
5. Verification steps

---

## Phase 1: Pre-Migration Backup

Before starting migration:

```bash
# Create backup of v2
cd /path/to/rilai-v2
git checkout -b v2-archive
git push origin v2-archive

# Create v3 branch
git checkout main
git checkout -b v3-migration
```

---

## Phase 2: Files to DELETE

### Core Module (entire rewrite)

```
src/rilai/core/
├── engine.py              # → Replaced by runtime/turn_runner.py
├── events.py              # → Replaced by contracts/events.py
├── stance.py              # → Replaced by contracts/workspace.py
├── stance_aggregator.py   # → Replaced by runtime/reducer.py
├── sensor_extractor.py    # → Replaced by runtime/stages.py
├── workspace_aggregator.py # → Replaced by runtime/workspace.py
├── memory_extractor.py    # → Replaced by memory/retrieval.py
├── critics_integration.py # → Replaced by runtime/critics.py
└── turn_state.py          # → Replaced by ui/projection.py
```

### Agencies Module (entire folder)

```
src/rilai/agencies/
├── __init__.py
├── base.py                # Agency base class (eliminated)
├── registry.py            # Agency registry (eliminated)
├── runner.py              # Agency runner (→ agents/executor.py)
└── messages.py            # Inter-agency messages (eliminated)
```

### Agents Module (partial)

```
src/rilai/agents/
├── protocol.py            # → Replaced by contracts/agent.py
└── base.py                # LLMAgent → agents/base.py (new)
```

### Council Module (entire folder)

```
src/rilai/council/
├── __init__.py
├── pipeline.py            # → Replaced by runtime/turn_runner.py
├── synthesizer.py         # → Replaced by runtime/council.py
├── deliberation.py        # → Replaced by runtime/deliberation.py
├── collector.py           # → Eliminated (claims in AgentOutput)
└── voice.py               # → Replaced by runtime/voice.py
```

### Brain Module

```
src/rilai/brain/
└── modulators.py          # → Replaced by runtime/modulators.py
```

### Memory Module (partial)

```
src/rilai/memory/
├── database.py            # → Replaced by store/event_log.py
└── short_term.py          # → Replaced by store/projections/
```

### Observability Module

```
src/rilai/observability/
└── store.py               # → Eliminated (dual-write removed)
```

### TUI Module

```
src/rilai/tui/
└── app.py                 # → Replaced by ui/app.py (complete rewrite)
```

### Sensors Module (partial)

```
src/rilai/sensors/
└── runner.py              # → Integrated into runtime/stages.py
```

### Data Directory (temporary storage)

```
data/
└── current/               # JSON ephemeral storage (eliminated)
```

---

## Phase 3: Files to KEEP and Modify

### CLI Entry Point

**File:** `src/rilai/cli.py`

**Changes:**
- Update imports to use new modules
- Modify `run` command to use `ui.app.RilaiApp`
- Modify `shell` command to use `runtime.TurnRunner`

### Providers

**File:** `src/rilai/providers/openrouter.py`

**Changes:**
- Keep existing functionality
- Add optional `embed()` method for embeddings
- Ensure `complete_streaming()` yields chunks properly

### Configuration

**Directory:** `src/rilai/config/`

**Changes:**
- Keep existing config structure
- Add new v3 settings:
  - `daemon_tick_interval`
  - `event_log_path`
  - `memory_db_path`

---

## Phase 4: New Directory Structure

After migration, the structure should be:

```
src/rilai/
├── __init__.py
├── cli.py                    # Modified
├── contracts/                # NEW
│   ├── __init__.py
│   ├── events.py
│   ├── agent.py
│   ├── sensor.py
│   ├── workspace.py
│   ├── council.py
│   └── memory.py
├── store/                    # NEW
│   ├── __init__.py
│   ├── event_log.py
│   └── projections/
│       ├── __init__.py
│       ├── base.py
│       ├── turn_state.py
│       ├── session.py
│       ├── analytics.py
│       └── debug.py
├── runtime/                  # NEW
│   ├── __init__.py
│   ├── turn_runner.py
│   ├── stages.py
│   ├── scheduler.py
│   ├── workspace.py
│   ├── reducer.py
│   ├── stance.py
│   ├── modulators.py
│   ├── deliberation.py
│   ├── argument_graph.py
│   ├── council.py
│   ├── voice.py
│   └── critics.py
├── agents/                   # REWRITTEN
│   ├── __init__.py
│   ├── manifest.py
│   ├── base.py
│   ├── executor.py
│   └── registry.py
├── memory/                   # REWRITTEN
│   ├── __init__.py
│   ├── retrieval.py
│   ├── episodic.py
│   ├── user_model.py
│   ├── consolidation.py
│   └── embeddings.py
├── daemon/                   # NEW
│   ├── __init__.py
│   ├── brain.py
│   ├── nudges.py
│   └── decay.py
├── ui/                       # REWRITTEN
│   ├── __init__.py
│   ├── app.py
│   ├── projection.py
│   └── panels/
│       ├── __init__.py
│       ├── chat.py
│       ├── sensors.py
│       ├── stance.py
│       ├── agents.py
│       ├── activity.py
│       └── critics.py
├── providers/                # KEPT
│   ├── __init__.py
│   └── openrouter.py
└── config/                   # KEPT
    ├── __init__.py
    └── settings.py

prompts/
└── agents/                   # REDESIGNED
    ├── emotion/
    │   ├── stress.yaml
    │   ├── stress.md
    │   ├── wellbeing.yaml
    │   ├── wellbeing.md
    │   └── ...
    ├── social/
    │   └── ...
    ├── planning/
    │   └── ...
    └── ... (all 49+ agents)
```

---

## Phase 5: Database Migration

### Event Log Schema

Create new SQLite database for events:

```sql
-- File: ~/.rilai/events.db

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    ts_monotonic REAL NOT NULL,
    ts_wall TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    UNIQUE(session_id, turn_id, seq)
);

CREATE INDEX idx_events_session_turn ON events(session_id, turn_id);
CREATE INDEX idx_events_kind ON events(kind);
CREATE INDEX idx_events_ts ON events(ts_wall);
```

### Memory Database Schema

Create memory database:

```sql
-- File: ~/.rilai/memory.db

-- Episodic events
CREATE TABLE episodic_events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    summary TEXT NOT NULL,
    emotions_json TEXT,
    topics_json TEXT,
    participants_json TEXT,
    importance REAL DEFAULT 0.5,
    embedding_json TEXT,
    turn_id INTEGER,
    session_id TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_episodic_timestamp ON episodic_events(timestamp DESC);
CREATE INDEX idx_episodic_importance ON episodic_events(importance DESC);

-- User facts
CREATE TABLE user_facts (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    source TEXT,
    first_seen TEXT,
    last_updated TEXT,
    mention_count INTEGER DEFAULT 1,
    embedding_json TEXT
);

CREATE INDEX idx_facts_category ON user_facts(category);
CREATE INDEX idx_facts_confidence ON user_facts(confidence DESC);

-- Goals/threads
CREATE TABLE user_goals (
    id TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT,
    deadline TEXT,
    priority INTEGER DEFAULT 1,
    progress REAL DEFAULT 0.0,
    notes TEXT
);

CREATE INDEX idx_goals_status ON user_goals(status);
```

### Data Migration Script

```python
"""migrate_v2_to_v3.py - One-time migration script."""

import sqlite3
import json
from pathlib import Path
from datetime import datetime


def migrate_conversations(old_db: Path, new_events_db: Path):
    """Migrate conversation history to event log format."""
    # This is optional - v3 starts fresh by default
    pass


def migrate_memory(old_db: Path, new_memory_db: Path):
    """Migrate existing memory data."""
    # Extract any saved user facts from v2
    # Convert to new schema format
    pass


def cleanup_old_data():
    """Remove old data directories."""
    old_dirs = [
        Path.home() / ".rilai" / "current",
        Path.home() / ".rilai" / "sessions",
    ]
    for d in old_dirs:
        if d.exists():
            import shutil
            shutil.rmtree(d)


if __name__ == "__main__":
    # Run migration
    migrate_conversations(
        Path.home() / ".rilai" / "rilai.db",
        Path.home() / ".rilai" / "events.db",
    )
    migrate_memory(
        Path.home() / ".rilai" / "rilai.db",
        Path.home() / ".rilai" / "memory.db",
    )
    print("Migration complete!")
```

---

## Phase 6: Agent Prompt Migration

All 49 agent prompts need to be redesigned. Each agent needs:

1. **YAML manifest** (`agent_name.yaml`)
2. **Markdown prompt** (`agent_name.md`)

### Agent Manifest Template

```yaml
id: agency.agent_name
display_name: Human Readable Name
description: What this agent does
inputs:
  - user_message
  - conversation_history
  - stance
outputs:
  - observation
  - claims
  - stance_delta
cost_estimate: 500  # tokens
cooldown: 30  # seconds
priority: normal  # always_on | monitor | normal
safety_profile: read_only
prompt_template: agent_name.md
version: 1
```

### Agent Prompt Template

```markdown
# Agent Name

Brief description of what you detect/analyze.

## Your Role
- Point 1
- Point 2
- Point 3

## What to Look For
- Signal 1
- Signal 2
- Signal 3

## Output Format (JSON)

```json
{
  "observation": "1-3 sentences of assessment",
  "urgency": 0-3,
  "confidence": 0-3,
  "claims": [
    {"text": "atomic claim", "type": "observation|recommendation|concern|question"}
  ],
  "stance_delta": {"dimension": delta}
}
```

### Urgency Scale
- 0: Nothing notable
- 1: Worth noting
- 2: Should address
- 3: Must respond to

### If Nothing to Report
```json
{"observation": "Quiet", "urgency": 0, "confidence": 0, "claims": []}
```
```

### Agents to Create (49 total)

**Emotion (5):**
- `emotion/stress.yaml` + `.md`
- `emotion/wellbeing.yaml` + `.md`
- `emotion/motivation.yaml` + `.md`
- `emotion/mood_regulator.yaml` + `.md`
- `emotion/wanting.yaml` + `.md`

**Social (5):**
- `social/relationships.yaml` + `.md`
- `social/empathy.yaml` + `.md`
- `social/norms.yaml` + `.md`
- `social/attachment_detector.yaml` + `.md`
- `social/mental_model.yaml` + `.md`

**Planning (4):**
- `planning/difference_engine.yaml` + `.md`
- `planning/short_term.yaml` + `.md`
- `planning/long_term.yaml` + `.md`
- `planning/priority.yaml` + `.md`

**Resource (3):**
- `resource/financial.yaml` + `.md`
- `resource/time.yaml` + `.md`
- `resource/energy.yaml` + `.md`

**Self (6):**
- `self/identity.yaml` + `.md`
- `self/values.yaml` + `.md`
- `self/meta_monitor.yaml` + `.md`
- `self/attachment_learner.yaml` + `.md`
- `self/reflection.yaml` + `.md`
- `self/self_model.yaml` + `.md`

**Reasoning (6):**
- `reasoning/debugger.yaml` + `.md`
- `reasoning/researcher.yaml` + `.md`
- `reasoning/reformulator.yaml` + `.md`
- `reasoning/analogizer.yaml` + `.md`
- `reasoning/creative.yaml` + `.md`
- `reasoning/magnitude.yaml` + `.md`

**Creative (3):**
- `creative/brainstormer.yaml` + `.md`
- `creative/synthesizer.yaml` + `.md`
- `creative/frame_builder.yaml` + `.md`

**Inhibition (3):**
- `inhibition/censor.yaml` + `.md`
- `inhibition/suppressor.yaml` + `.md`
- `inhibition/exception_handler.yaml` + `.md`

**Monitoring (4):**
- `monitoring/trigger_watcher.yaml` + `.md`
- `monitoring/anomaly_detector.yaml` + `.md`
- `monitoring/interrupt_manager.yaml` + `.md`
- `monitoring/attention.yaml` + `.md`

**Execution (6):**
- `execution/executor.yaml` + `.md`
- `execution/habits.yaml` + `.md`
- `execution/script_runner.yaml` + `.md`
- `execution/context_manager.yaml` + `.md`
- `execution/output_filter.yaml` + `.md`
- `execution/general_responder.yaml` + `.md`

---

## Phase 7: Verification Checklist

### Unit Tests

Run after each document implementation:

```bash
# Run all tests
pytest tests/

# Run specific module tests
pytest tests/test_contracts.py
pytest tests/test_event_store.py
pytest tests/test_runtime.py
pytest tests/test_agents.py
pytest tests/test_deliberation.py
pytest tests/test_council.py
pytest tests/test_memory.py
pytest tests/test_ui.py
pytest tests/test_daemon.py
```

### Integration Tests

```bash
# Test full turn pipeline
pytest tests/integration/test_turn_pipeline.py

# Test event replay
pytest tests/integration/test_event_replay.py

# Test TUI rendering
pytest tests/integration/test_tui.py
```

### Manual Verification

1. **Start TUI:**
   ```bash
   rilai
   ```
   - Verify panels render correctly
   - Verify input works
   - Send a message and verify all stages complete

2. **Check Event Log:**
   ```bash
   sqlite3 ~/.rilai/events.db "SELECT kind, COUNT(*) FROM events GROUP BY kind"
   ```
   - Verify events are being logged

3. **Check Panel Updates:**
   - Send a message
   - Verify sensors panel updates
   - Verify stance panel updates
   - Verify agent log shows activity
   - Verify response appears in chat

4. **Test Daemon:**
   - Start TUI
   - Wait 30+ seconds
   - Verify daemon tick events in log
   - Set high strain manually and verify nudge

5. **Test Memory:**
   - Have a conversation
   - Restart rilai
   - Verify context is retrieved

---

## Phase 8: Cleanup

### Remove Old Files

```bash
# After verification, remove old v2 files
rm -rf src/rilai/core/
rm -rf src/rilai/agencies/
rm -rf src/rilai/council/
rm -rf src/rilai/brain/
rm -f src/rilai/agents/protocol.py
rm -f src/rilai/memory/database.py
rm -f src/rilai/memory/short_term.py
rm -f src/rilai/observability/store.py
rm -f src/rilai/sensors/runner.py
rm -rf src/rilai/tui/  # Old TUI
rm -rf data/current/
```

### Update pyproject.toml

```toml
[project]
name = "rilai"
version = "3.0.0"
description = "Event-sourced cognitive companion"
# ... rest of config
```

### Git Cleanup

```bash
git add .
git commit -m "Complete v3 migration"
git push origin v3-migration

# After testing, merge to main
git checkout main
git merge v3-migration
git tag v3.0.0
git push origin main --tags
```

---

## Success Criteria

The migration is complete when:

1. **`rilai` command starts TUI** with all panels functional
2. **`rilai shell` works** with event-sourced pipeline
3. **All panels update in real-time** (not batched at end)
4. **Event log is replayable** (can rebuild UI state from events)
5. **Background daemon emits** tick and nudge events
6. **Memory retrieval** injects context before agents
7. **All 49+ agents** output structured JSON
8. **No dual-write** - single SQLite event log
9. **All tests pass** with good coverage
10. **No references to deleted v2 modules**

---

## Rollback Plan

If migration fails:

```bash
# Return to v2
git checkout v2-archive
pip install -e .

# Restore data
cp -r ~/.rilai.backup ~/.rilai
```

Always maintain `v2-archive` branch until v3 is stable in production.

---

## Document Complete

This completes the Rilai v3 implementation plan. Execute documents 00-10 in order, then use this document for final migration and cleanup.

Total estimated implementation time: ~36 hours across 12 documents.
