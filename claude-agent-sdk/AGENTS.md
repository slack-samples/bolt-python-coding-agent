# AGENTS.md

Guidance for coding agents working in this directory. Refer to the root `../AGENTS.md` for repository-wide structure and commands.

## Claude Agent SDK specifics

**Agents (`agent/agent.py`)** are two sets of `ClaudeAgentOptions` with pinned models: a routing agent (`claude-haiku-4-5`) whose only tool is `create_code_channel`, and the coding agent (`claude-sonnet-5-5`) with every other tool. Tools are async `@tool` functions, one per file under `agent/tools/`, each with a JSON Schema for its arguments. They're served in-process by `create_sdk_mcp_server()`, so the model sees each as `mcp__coding-agent__<name>`. Both agents set `tools=[]`, `setting_sources=[]`, and `strict_mcp_config=True`, so they get none of Claude Code's built-in tools and none of the settings, `CLAUDE.md` files, or MCP servers on the machine. `verbatim_prompts=True` keeps an `@path` in a Slack message from reading a local file.

**Deps** reach the tools and hooks through `current_deps` in `agent/sessions.py`, a `ContextVar`, since the SDK calls a tool with only its arguments. `_run` in `agent/agent.py` sets it before the client starts, so the tasks the client starts see it.

**Runs** use a `ClaudeSDKClient` per run from async Bolt listeners, which runs the Claude Code CLI bundled with the SDK. Coding turns allow `MAX_TURNS` model calls, and a turn that uses them all (`error_max_turns`) ends with a message, keeping its history. A `PostToolUse` hook returns `continue_: False` to end the run early once there's nothing left to do: after `create_code_channel` succeeds for the routing agent, and after `archive_channel` for the coding agent. A result with `is_error` raises, so the turn posts a warning.

**Turns** go through `agent/turns.py`, which doesn't import the SDK. A turn that raises posts a warning and moves the session back to `active`, keeping the history from the last finished turn. Model-written replies use `markdown_text`, since the model writes standard markdown.

**Stopping** sets `session.stopped`, and so does archiving the channel from Slack. The `PreToolUse` hook from `gate_tool_calls` (`agent/guardrails.py`) then denies every tool call and tells the model to wrap up, and the turn posts nothing when it finishes.

**Conversation history** lives in the Claude Code session transcript. `session.history` is the list of each run's `ResultMessage`, and the next run resumes from the last one's `session_id`.

**Command approvals.** The `PreToolUse` hook wraps `command_needs_approval()` from `agent/approvals.py` and returns `defer` for a `run_command` that needs approval, which ends the run with `deferred_tool_use` on its result. A paused run is a `PausedRun` (its history, ending with that result), parked in `pending_store` with the ts of its Approve/Deny message, so a click only resumes the run its buttons were posted for. `resume_run` resumes the session without a prompt: the CLI asks the hook about the waiting call again, and the hook answers with the decision. A newer message in the channel retires a pending approval, so a late click can't resume an older run over it. The next run then finds the waiting call on the last result, and the hook hands it to `answer_unanswered`, the `can_use_tool` callback, which denies it as not run and interrupts that old turn, so no model call is spent on it before the new message.

## Testing

Tests are async (`pytest-asyncio` in auto mode) and mock the Slack client with `Mock(AsyncWebClient)`. When mocking SDK objects, use `Mock(spec=...)` or `MagicMock(spec=...)` with the real class (`ClaudeSDKClient`), or build the real dataclass (`ResultMessage`), so a call to a method that doesn't exist fails the test. `tests/test_runs.py` runs the real agents and the bundled CLI against `tests/fake_model.py`, a local stand-in for the Anthropic Messages API that returns scripted tool calls and replies, so the SDK seams are tested without calling Anthropic.
