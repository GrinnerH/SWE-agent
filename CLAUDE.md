# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SWE-agent is an Agent Computer Interface (ACI) system that enables language models to autonomously fix issues in GitHub repositories, solve coding challenges, and perform cybersecurity tasks. It uses configurable interfaces to interact with isolated computing environments.

## Common Development Commands

### Setup and Installation
```bash
# Install in development mode
pip install -e .

# Install with development dependencies
pip install -e ".[dev]"
```

### Testing
```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov

# Run tests in parallel
pytest -n auto

# Run specific test markers
pytest -m "not slow"  # Skip slow tests
pytest -m ctf        # Run CTF-related tests only
```

### Linting and Formatting
```bash
# Run ruff linter with auto-fix
ruff check --fix

# Run ruff formatter
ruff format

# Run pre-commit hooks on all files
pre-commit run --all-files

# Check for typos
typos
```

### Running SWE-agent
```bash
# Run on a single issue
sweagent run

# Run in batch mode (e.g., SWE-Bench)
sweagent run-batch

# Inspect trajectories
sweagent inspect <trajectory_file>

# Start web-based trajectory inspector
sweagent inspector

# Run API server for web UI
sweagent run-api
```

## Architecture Overview

### Core Components

**Agent System (`sweagent/agent/`)**:
- `agents.py`: Main agent logic and execution loop
- `models.py`: Model interfaces (LiteLLM integration, human interaction)
- `action_sampler.py`: Action sampling strategies
- `history_processors.py`: Context management and history processing
- `problem_statement.py`: Problem statement parsing and formatting

**Environment System (`sweagent/environment/`)**:
- `swe_env.py`: Main environment interface using SWE-ReX
- `repo.py`: Repository management and cloning logic
- Integrates with containerized execution environments

**Tools System (`tools/`)**:
- Modular tool bundles with `config.yaml` and `bin/` directories
- Default tools: file navigation, editing, search
- Specialized tools: linting, review, submission
- Each tool has install scripts and configuration

**Configuration System (`config/`)**:
- YAML-based configuration files for different agent modes
- Template system using Jinja2 for prompts
- Supports function calling and thought-action patterns

### Key Architectural Patterns

**Tool Bundles**: Tools are organized as self-contained bundles with:
- `config.yaml`: Tool definitions, signatures, and documentation
- `bin/`: Executable scripts
- `install.sh`: Setup scripts
- `lib/`: Shared utilities

**Agent-Computer Interface (ACI)**: The system provides a controlled interface between language models and computing environments through:
- Windowed file editing with context management
- Bash command execution with proper error handling
- Tool function calls with structured arguments

**Configuration-Driven Design**: Behavior is controlled through YAML configs that define:
- Agent templates and prompts
- Tool availability and configuration
- Environment setup and deployment options
- Model parameters and retry logic

### Data Flow

1. **Problem Statement** → Parsed and formatted by `ProblemStatement`
2. **Agent** → Uses configured tools and models to generate actions
3. **Environment** → Executes actions in containerized environment via SWE-ReX
4. **History Processing** → Manages context and conversation history
5. **Trajectory Storage** → Saves execution traces for replay/analysis

## Development Notes

- **Python Version**: Requires Python 3.11+
- **Dependencies**: Uses SWE-ReX (≥1.2.0) for environment management
- **Testing**: Extensive test suite with fixtures in `tests/test_data/`
- **Documentation**: Built with MkDocs, source in `docs/`
- **Code Quality**: Enforced via ruff, pre-commit hooks, and CI/CD

## File Organization

- `sweagent/run/`: CLI entry points and execution logic
- `sweagent/utils/`: Shared utilities (logging, config, serialization)
- `tools/`: Modular tool system with various editing/analysis tools
- `config/`: Agent configuration files and templates
- `tests/`: Comprehensive test suite with data sources and trajectories
- `docs/`: Documentation source files