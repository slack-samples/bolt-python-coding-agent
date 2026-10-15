# AGENTS.md

Guidance for coding agents working in this directory. Refer to the root `../AGENTS.md` for repository-wide structure and commands.

## OpenAI Agents SDK specifics

**Agents (`agent/agent.py`)** are two `Agent`s with pinned models: a routing `request_agent` (`gpt-6-luna`) whose only tool is `create_code_channel`, and the coding `agent` (`gpt-6.1-sol`) with every other tool. Tools are async `@function_tool` functions, one per file under `agent/tools/`, that read `RunContextWrapper[AgentDeps]` (or `RequestDeps`) for the Slack client and session. Both agents set `ModelSettings(truncation="auto")`, so a long session drops its oldest conversation instead of outgrowing the context window.

**Runs** use `await Runner.run()` from async Bolt listeners. Coding turns allow `MAX_TURNS` model calls, and a turn that uses them all ends with a message through the SDK's `max_turns` error handler, so its history is kept. Each agent's `tool_use_behavior` ends the run early once there's nothing left to do: after `create_code_channel` succeeds for the routing agent, and after `archive_channel` for the coding agent.

**Turns** go through `agent/turns.py`, which doesn't import the SDK. A turn that raises posts a warning and moves the session back to `active`, keeping the history from the last finished turn. Model-written replies use `markdown_text`, since the model writes standard markdown.

**Stopping** sets `session.stopped`. Every code channel tool lists the `session_stopped` tool input guardrail (`agent/guardrails.py`), which skips the call and tells the model to wrap up, and the turn posts nothing when it finishes.

**Conversation history** comes from `result.to_input_list()` and is stored on the `CodeChannelSession` (`agent/store.py`), keyed by code channel. Follow-up turns pass `session.history + [{"role": "user", "content": text}]`.

**Command approvals.** `run_command_needs_approval` in `agent/guardrails.py` wraps `command_needs_approval()` from `agent/approvals.py` in the SDK's `needs_approval` hook for `run_command`. A paused run is a `PausedRun` (the `RunState` and its `ToolApprovalItem`), parked in `pending_store` with the ts of its Approve/Deny message, so a click only resumes the run its buttons were posted for. A newer message in the channel retires a pending approval, so a late click can't resume an older run over it.

## Testing

Tests are async (`pytest-asyncio` in auto mode) and mock the Slack client with `Mock(AsyncWebClient)`. When mocking SDK objects, use `Mock(spec=...)` with the real class (`RunResult`, `RunState`, `ToolApprovalItem`) so a call to a method that doesn't exist fails the test. `tests/test_runs.py` runs the real agents against `tests/fake_model.py`, a model that returns scripted tool calls and replies, so the SDK seams are tested without calling OpenAI.
