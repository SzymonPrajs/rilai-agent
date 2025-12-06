# Rilai v2

Cognitive architecture for AI companionship - a Society of Mind implementation with Textual TUI.

## Quick Start

```bash
# Copy config and add your API key
cp config.example.py config.py
# Edit config.py with your OpenRouter API key

# Install
pip install -e .

# Run
rilai
```

## Architecture

Rilai implements a Society of Mind architecture where multiple specialized agents
evaluate input from different perspectives, then a council synthesizes their views
into a unified response.

### Key Features

- **10 Agencies, 49+ Agents**: Specialized cognitive modules covering emotion, planning,
  social, reasoning, and more
- **Multi-Round Deliberation**: Agents can hear each other and adjust their positions
- **Thinking Model Support**: Native support for reasoning tokens (DeepSeek R1, Claude :thinking)
- **Textual TUI**: Beautiful terminal interface with live status
- **Slash Commands**: `/clear`, `/status`, `/query` and more
- **Dual Storage**: SQLite (permanent) + JSON (dev-friendly)

### Agency Architecture

```
COUNCIL (synthesis)
├── GOAL-ORIENTED
│   ├── PLANNING   [Difference-Engine, Short-term, Long-term, Priority]
│   ├── RESOURCE   [Financial, Time, Energy]
│   └── SELF       [Identity, Values, Meta-Monitor, ...]
├── EVALUATIVE
│   ├── EMOTION    [Wellbeing, Stress, Motivation, ...]
│   └── SOCIAL     [Relationships, Empathy, Norms, ...]
├── PROBLEM-SOLVING
│   ├── REASONING  [Debugger, Researcher, Reformulator, ...]
│   └── CREATIVE   [Brainstormer, Synthesizer, Frame-Builder]
├── CONTROL
│   ├── INHIBITION [Censor, Suppressor, Exception-Handler]
│   └── MONITORING [Trigger-Watcher, Anomaly-Detector, ...]
└── ACTION
    └── EXECUTION  [Executor, Habits, Script-Runner, ...]
```

## CLI Commands

```bash
rilai                     # Launch TUI (default)
rilai shell               # Interactive REPL (no TUI)
rilai clear current       # Clear current session
rilai clear sessions      # Clear all sessions
rilai clear all           # Clear everything
rilai status              # Show system status
rilai query agent-calls   # Query agent logs
rilai query stats         # Show statistics
```

## Configuration

Edit `config.py` (copy from `config.example.py`):

```python
OPENROUTER_API_KEY = "sk-or-v1-..."

MODELS = {
    "small": "meta-llama/llama-3.1-8b-instruct",
    "medium": "meta-llama/llama-3.3-70b-instruct",
    "large": "deepseek/deepseek-chat",
}

THINKING_MODELS = {
    "small": "deepseek/deepseek-r1-distill-qwen-7b",
    "medium": "anthropic/claude-3.5-sonnet:thinking",
    "large": "deepseek/deepseek-r1",
}
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

## License

MIT
