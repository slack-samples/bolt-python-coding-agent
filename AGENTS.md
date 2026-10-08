# AGENTS.md

Guidance for coding agents working in this repository.

## What this is

A monorepo for a **Coding Agent** sample for Slack, built with Bolt for Python. Each framework lives in its own directory as a standalone sample:

- `openai-agents-sdk/` — built with the **OpenAI Agents SDK**

Implementations share a structure and user experience, not code. Keep each one obvious on its own, written in its framework's idiom, rather than adding shared helpers.

## Commands

Run these from inside an implementation directory, such as `openai-agents-sdk/`:

```sh
# Run the app (requires .env with the framework's API key; Slack tokens are optional with the CLI)
slack run          # via Slack CLI
python3 app.py     # directly

# Lint and format (CI runs these on push to main and all PRs)
ruff check .
ruff format --check .

# Run tests
pytest
```

## Repository structure

```
.github/             # Shared CI workflows and dependabot config
openai-agents-sdk/   # OpenAI Agents SDK implementation
```

CI runs ruff and pytest against each directory with a matrix in `.github/workflows/ruff.yml` and `.github/workflows/tests.yml`. Dependabot watches each directory separately. When adding an implementation, add its directory to both workflow matrices, to `.github/dependabot.yml`, and to the framework table in the root `README.md`.

## Architecture

Three layers: **app.py** -> **listeners/** -> **agent/**.

- **`app.py`** starts Bolt in Socket Mode and calls `register_listeners(app)`. **`app_oauth.py`** is the alternative entry point for OAuth over HTTP.
- **`listeners/`** holds Bolt handlers only, grouped by Slack feature (`actions/`, `commands/`, `events/`). Each sub-package has a `register(app)` function.
- **`agent/`** holds everything else: the agents and their prompts, one file per tool under `agent/tools/`, the session store, and command approvals.

The flow: a mention outside a code channel runs a small routing agent that either replies in the thread or calls `create_code_channel`. Slack seeds the new channel with the request, and that mention starts the coding agent's first turn there. Every later message, slash command, and approval in the channel runs a turn of the same session.

Refer to each implementation's README for its specifics.
