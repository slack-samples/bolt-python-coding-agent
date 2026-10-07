# AGENTS.md

Guidance for coding agents working in this directory. Refer to the root `../AGENTS.md` for repository-wide structure and commands.

## OpenAI Agents SDK specifics

**Agents (`agent/agent.py`)** are two `Agent`s with pinned models: a routing `request_agent` (`gpt-6-luna`) whose only tool is `create_code_channel`, and the coding `agent` (`gpt-6.1-sol`) with every other tool. Tools are `@function_tool` functions, one per file under `agent/tools/`, that read `RunContextWrapper[AgentDeps]` (or `RequestDeps`) for the Slack client and session.

**Runs** use `Runner.run_sync()` from sync Bolt listeners. Each Bolt worker thread gets its own `AsyncOpenAI` client through `_run_config()`, because `run_sync` drives each run on that thread's event loop and the SDK's default client is shared across the process. Coding turns allow `MAX_TURNS` model calls.

**Turns** go through `run_turn()` and `resume_turn()` in `agent/agent.py`, which set the session status, run the agent, and post the outcome. Model-written replies use `markdown_text`, since the model writes standard markdown.

**Conversation history** comes from `result.to_input_list()` and is stored on the `CodeChannelSession` (`agent/store.py`), keyed by code channel. Follow-up turns pass `session.history + [{"role": "user", "content": text}]`.

**Command approvals (`agent/approvals.py`)** use the SDK's `needs_approval` hook on `run_command`. A paused run is parked in `pending_store` with the ts of its Approve/Deny message, so a click only resumes the run its buttons were posted for.

## Testing

Tests mock the Slack client and the agent runs. When mocking SDK objects, use `Mock(spec=...)` with the real class (`RunResult`, `RunState`, `ToolApprovalItem`) so a call to a method that doesn't exist fails the test.
