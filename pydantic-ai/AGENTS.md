# AGENTS.md

Guidance for coding agents working in this directory. Refer to the root `../AGENTS.md` for repository-wide structure and commands.

## Slack plugin

To install the Slack plugin for your coding agent, follow [Claude Code, Codex, Cursor, and Other Coding Agents](./README.md#claude-code-codex-cursor-and-other-coding-agents) in the README.

## Pydantic AI specifics

**Agents (`agent/agent.py`)** are two Pydantic AI `Agent`s: a routing `request_agent` whose only tool is `create_code_channel`, and the coding `agent` with every other tool. Neither sets a model. A `SelectModel` capability picks one when a run starts, by which API key is set: Anthropic (`claude-haiku-4-5` to route, `claude-sonnet-5-5` to code) when `ANTHROPIC_API_KEY` is set, else OpenAI (`gpt-6-luna` and `gpt-6.1-sol`). So no model client is created at import. Tools are async functions, one per file under `agent/tools/`, passed with `tools=[...]`. Each takes `RunContext[AgentDeps]` (or `RequestDeps`, both in `agent/sessions.py`) for the Slack client and session, and Pydantic AI reads its docstring for the description the model sees. The coding agent lists `AnthropicCompaction` and `OpenAICompaction`, so a long session compacts its oldest conversation instead of outgrowing the context window. Each only applies to its own provider's models.

**Ending a run.** `create_code_channel` and `archive_channel` are output functions (`ToolOutput`), not plain tools, so a successful call ends the run as its output with no further model call. That's Pydantic AI's way to end a run with a tool call. A Slack error in either raises `ModelRetry`, which sends the error back to the model to recover from, such as by replying in place.

**Runs** go through `agent.iter()` from async Bolt listeners. Coding turns allow `MAX_TURNS` model requests with `UsageLimits`. A turn that uses them all ends with a message, and keeps its history by reading the run's messages when `UsageLimitExceeded` is raised.

**Turns** go through `agent/turns.py`, which doesn't import Pydantic AI. A turn that raises posts a warning and moves the session back to `active`, keeping the history from the last finished turn. A tool that raises doesn't fail the turn: the `tool_execute_error` hook logs it and tells the model the tool failed with `ToolFailed`. Model-written replies use `markdown_text`, since the model writes standard markdown.

**Stopping** sets `session.stopped`, and so does archiving the channel from Slack. The `guardrails` capability (`agent/guardrails.py`) skips every tool call once it's set, with `SkipToolExecution`, and tells the model to wrap up. `archive_channel` is an output function, so a hook on the output does the same for it. The turn posts nothing when it finishes.

**Conversation history** is the run's `all_messages()`, a `list[ModelMessage]` stored on the `CodeChannelSession` (`agent/sessions.py`), keyed by code channel. Follow-up turns pass it as `message_history` with the new text as the prompt.

**Command approvals.** `run_command_needs_approval` in `agent/guardrails.py` is a `before_tool_execute` hook for `run_command` that raises `ApprovalRequired` when `command_needs_approval()` from `agent/approvals.py` says so. That ends the run with `DeferredToolRequests` as its output. A paused run is a `PausedRun` (the messages, the requests, and the usage so far), parked in `pending_store` with the ts of its Approve/Deny message, so a click only resumes the run its buttons were posted for. Resuming passes `deferred_tool_results` with `True` or a `ToolDenied`, and the usage, so the turn keeps counting toward `MAX_TURNS`. Every pending call needs an answer, so if one step asked for more than one command, the others are answered as not run and the model can ask again. A newer message in the channel retires a pending approval, so a late click can't resume an older run over it.

## Testing

Tests are async (`pytest-asyncio` in auto mode) and mock the Slack client with `Mock(AsyncWebClient)`. When mocking Pydantic AI objects, use `Mock(spec=...)` with the real class (`AgentRunResult`) so a call to a method that doesn't exist fails the test. `tests/test_runs.py` runs the real agents against `tests/fake_model.py`, a `FunctionModel` that returns scripted tool calls and replies, swapped in with `Agent.override`, so the Pydantic AI seams are tested without calling a provider. `models.ALLOW_MODEL_REQUESTS = False` in `tests/conftest.py` keeps a test from reaching a real model by mistake.
