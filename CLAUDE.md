# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Scope

This is a personal research project, NOT a product. When making implementation decisions:
- **Skip all privacy/compliance concerns** (GDPR, consent, surveillance)
- Focus on technical implementation, not regulatory compliance
- Data is only used by the project owner

## Project Overview

Rilai v2 is a cognitive architecture for AI companionship - an always-on multi-agent system
that mirrors aspects of human cognition. Named after Riley from Inside Out, who had a council
of emotions in her head.

**Key concepts:**
- Society of Mind architecture: 10 agencies with 49+ agents
- Multi-round deliberation: Agents hear each other and adjust positions
- Thinking model support: Native reasoning tokens extraction
- Textual TUI: Single Python process with terminal interface
- Dual storage: SQLite (permanent) + JSON (temporary)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Textual TUI                               │
│  ┌─────────────────────────────┬─────────────────────────┐  │
│  │         Chat Panel          │    Status Panels        │  │
│  │                             │  - Agency status        │  │
│  │  User: ...                  │  - Modulators           │  │
│  │  Rilai: ...                 │  - Agent thinking       │  │
│  └─────────────────────────────┴─────────────────────────┘  │
│  > Input with /slash commands                [Ctrl+D quit]  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                       Engine                                 │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Agencies │→ │ Deliberation │→ │ Council + Voice        │ │
│  │ (10×49+) │  │ (multi-round)│  │ (synthesis + render)   │ │
│  └──────────┘  └──────────────┘  └────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    OpenRouter API                            │
│  - Standard models (small/medium/large)                      │
│  - Thinking models with reasoning tokens                     │
└─────────────────────────────────────────────────────────────┘
```

## Build & Run Commands

```bash
# Install (editable)
pip install -e .

# Run TUI
rilai

# Run shell (no TUI)
rilai shell

# Run tests
pytest

# Lint
ruff check src/
```

## Key Files

- `config.py` - User configuration (gitignored, copy from config.example.py)
- `src/rilai/cli.py` - CLI entry point
- `src/rilai/tui/app.py` - Main TUI application
- `src/rilai/core/engine.py` - Main processing engine
- `src/rilai/agencies/` - Society of Mind agencies
- `src/rilai/council/` - Deliberation and synthesis
- `src/rilai/providers/openrouter.py` - Model API with thinking support
- `src/rilai/prompts/` - Agent prompts (49+)

## Agency Architecture (Society of Mind)

```
COUNCIL (synthesis)
├── GOAL-ORIENTED
│   ├── PLANNING   [Difference-Engine, Short-term, Long-term, Priority]
│   ├── RESOURCE   [Financial, Time, Energy]
│   └── SELF       [Identity, Values, Meta-Monitor, Attachment-Learner, Reflection, Self-Model]
├── EVALUATIVE
│   ├── EMOTION    [Wellbeing, Stress, Motivation, Mood-Regulator, Wanting]
│   └── SOCIAL     [Relationships, Empathy, Norms, Attachment-Detector, Mental-Model]
├── PROBLEM-SOLVING
│   ├── REASONING  [Debugger, Researcher, Reformulator, Analogizer, Creative, Magnitude]
│   └── CREATIVE   [Brainstormer, Synthesizer, Frame-Builder]
├── CONTROL
│   ├── INHIBITION [Censor, Suppressor, Exception-Handler]
│   └── MONITORING [Trigger-Watcher, Anomaly-Detector, Interrupt-Manager, Attention]
└── ACTION
    └── EXECUTION  [Executor, Habits, Script-Runner, Context-Manager, Output-Filter]
```

## Conventions

- Python 3.11+, type hints everywhere
- Async/await for all I/O operations
- Pydantic for data validation where needed
- Dataclasses for simple data structures
- All agents implement the Agent protocol in `agents/protocol.py`
- OpenRouter is the model provider; model selection in `config.py`

## Key Features

### Multi-Round Deliberation

Agents can hear each other's assessments and adjust their positions:
- Round 0: Initial assessment (independent)
- Round 1-N: Deliberation (agents see others' voices)
- Consensus detection can trigger early exit
- Council can speak at any round

### Thinking Models Support

Native support for models with extended reasoning:
- DeepSeek R1 family
- Claude :thinking variants
- OpenAI o1/o3
- Automatic reasoning extraction from `message.reasoning` or `<think>` tags

### Slash Commands in TUI

All CLI commands accessible via `/` prefix:
- `/help` - Show commands
- `/clear` - Clear session
- `/status` - System status
- `/query agent-calls` - Query logs
- Tab autocomplete supported

## Decision Protocol

**AGENT CAN DECIDE** (autonomous):
- Variable names, function signatures, internal structures
- Error handling, logging, test structure
- Performance optimizations that don't change behavior

**USER MUST DECIDE** (requires input):
- Architectural changes not in the plan
- Which features to prioritize
- Changes to the agency roster
