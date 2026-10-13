# AGENTS.md

Guidance for coding agents working in this directory. Refer to the root `../AGENTS.md` for repository-wide structure and commands.

## OpenAI Agents SDK specifics

**Agents (`agent/agent.py`)** are two `Agent`s with pinned models: a routing `request_agent` (`gpt-6-luna`) whose only tool is `create_code_channel`, and the coding `agent` (`gpt-6.1-sol`) with every other tool. Tools are `@function_tool` functions, one per file under `agent/tools/`, that read `RunContextWrapper[AgentDeps]` (or `RequestDeps`) for the Slack client and session.

**Runs** use `Runner.run_sync()` from sync Bolt listeners. Each Bolt worker thread gets its own `AsyncOpenAI` client through `_run_config()`, because `run_sync` drives each run on that thread's event loop and the SDK's default client is shared across the process. Coding turns allow `MAX_TURNS` model calls.

**Turns** go through `agent/turns.py`, which doesn't import the SDK. `run_turn()`, `resume_turn()`, and `stop_turn()` set the session status, call `start_run()` / `resume_run()` in `agent/agent.py`, and post the outcome. A turn that raises posts a warning and moves the session back to `active`, keeping the history from the last finished turn. A turn that uses every one of `MAX_TURNS` model calls ends with a message through the SDK's `max_turns` error handler, so its history is kept. Model-written replies use `markdown_text`, since the model writes standard markdown.

**Stopping** sets `session.stopped`. Every code channel tool lists the `session_stopped` tool input guardrail (`agent/guardrails.py`), which skips the call and tells the model to wrap up, and the turn posts nothing when it finishes.

**Conversation history** comes from `result.to_input_list()` and is stored on the `CodeChannelSession` (`agent/store.py`), keyed by code channel. Follow-up turns pass `session.history + [{"role": "user", "content": text}]`.

**Command approvals.** `command_needs_approval()` in `agent/approvals.py` lets only read-only commands run without asking, and asks for anything with shell syntax like `&&` or `|`. `run_command` wraps it in the SDK's `needs_approval` hook. A paused run is a `PausedRun` (the `RunState` and its `ToolApprovalItem`), parked in `pending_store` with the ts of its Approve/Deny message, so a click only resumes the run its buttons were posted for. A newer message in the channel retires a pending approval, so a late click can't resume an older run over it.

## Testing

Tests mock the Slack client and the agent runs. When mocking SDK objects, use `Mock(spec=...)` with the real class (`RunResult`, `RunState`, `ToolApprovalItem`) so a call to a method that doesn't exist fails the test.
