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

- **`app.py`** starts Bolt's `AsyncApp` in Socket Mode and calls `register_listeners(app)`. **`app_oauth.py`** is the alternative entry point for OAuth over HTTP, where agent slash commands arrive at the manifest's `code_channels.slash_command_url`. Everything is async, so a long turn never holds up the stop button, an approval click, or another channel.
- **`listeners/`** holds Bolt handlers only, grouped by Slack feature (`actions/`, `commands/`, `events/`). Each sub-package has a `register(app)` function.
- **`agent/`** holds everything else: the agents and their prompts, one file per tool under `agent/tools/`, the turn handling, the sessions and the deps each run gets, and command approvals.

The flow: a mention or direct message outside a code channel runs a small routing agent that either replies in place or calls `create_code_channel`. Slack seeds the new channel with the request, and that mention starts the coding agent's first turn there, along with the conversation the request came from. Every later message, slash command, and approval in the channel runs a turn of the same session. Messages sent while a turn runs wait and go into the next turn together.

## Keeping implementations alike

Implementations share structure, not code, so these parts are kept the same by copying them and changing them everywhere at once:

- **The seam between `listeners/` and `agent/`.** Listeners import only from the `agent` package, never from the agent framework, so `listeners/` is the same in every implementation. `agent/__init__.py` provides `answer_request`, `find_session`, `run_turn`, `resume_turn`, `stop_turn`, and `end_session`.
- **Framework-free files.** `agent/turns.py`, `agent/context.py`, `agent/approvals.py`, `agent/sessions.py`, `agent/workspace.py`, `agent/outcome.py`, and `agent/prompts.py` don't import the agent framework. The framework lives in `agent/agent.py`, `agent/guardrails.py`, and `agent/tools/`. `turns.py` calls only `run_request(prompt, deps)`, which returns the reply text, and `start_run(history, text, deps)` and `resume_run(paused, approved, deps)`, which return the `RunOutcome` in `agent/outcome.py`. The paused run is a handle `turns.py` passes back without looking inside, so each framework's way of pausing fits behind it.
- **What the framework side keeps true.** `turns.py` relies on these, so every implementation keeps them: `create_code_channel` sets `deps.code_channel_id`, and `archive_channel` sets `session.archived`. Every code channel tool skips its call once `session.stopped` is set. A paused run's history already records the pending command as not run, so `turns.py` can drop a paused run without resuming it. Beyond that, `turns.py` only checks whether `history` is empty, to know a turn is the first.
- **Prompts.** `agent/prompts.py` is the same word for word in every implementation.
- **Tools.** Every implementation offers the same tools with the same names, arguments, and descriptions, written with its framework's tool decorator. File tools stay inside the clone and can't write into `.git`.
- **Command approvals.** `command_needs_approval(command)` is plain Python and the same in every implementation, wrapped in the framework's own approval hook. Read-only commands and local git changes run without asking. Anything that runs the repository's code or reaches outside the clone asks first. Commands run without a shell, so the check and the run split a command the same way. On Windows, `.cmd` and `.bat` programs like `npm` are the exception, since Windows runs them through `cmd.exe`.
- **Tests.** Test files and names mirror each other, and `tests/test_runs.py` drives real agent runs with a scripted model to cover pausing, resuming, stopping, and running out of turns.

Refer to each implementation's README for its specifics.
