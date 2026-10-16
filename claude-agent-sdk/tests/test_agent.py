from unittest.mock import MagicMock, Mock, patch

import pytest
from claude_agent_sdk import (
    ClaudeSDKClient,
    DeferredToolUse,
    HookContext,
    PreToolUseHookInput,
    ResultMessage,
)

from agent.agent import MAX_TURNS, PausedRun, _settle, resume_run
from agent.sessions import AgentDeps, CodeChannelSession


def result(**fields) -> ResultMessage:
    """A run's result, completed unless `fields` say otherwise."""
    return ResultMessage(
        **{
            "subtype": "success",
            "duration_ms": 1,
            "duration_api_ms": 1,
            "is_error": False,
            "num_turns": 1,
            "session_id": "session-1",
            "result": "Done.",
            **fields,
        }
    )


def deferred(command: str = "rm -rf build") -> ResultMessage:
    """The result of a run that ended on a command waiting for approval."""
    return result(
        result="",
        terminal_reason="tool_deferred",
        deferred_tool_use=DeferredToolUse(
            id="toolu_1",
            name="mcp__coding-agent__run_command",
            input={"command": command},
        ),
    )


class TestSettle:
    def test_completed_run_keeps_its_history(self):
        earlier = result(session_id="session-1")
        done = result()

        outcome = _settle([earlier], done)

        assert outcome.final_output == "Done."
        assert outcome.needs_approval is False
        assert outcome.history == [earlier, done]

    def test_paused_run_leaves_the_pending_call_for_the_next_run_to_answer(self):
        paused = deferred()

        outcome = _settle([], paused)

        assert outcome.paused.history == [paused]
        assert outcome.command == "rm -rf build"
        # A stopped or replaced run leaves this history behind, and the next
        # run answers its waiting call as not run.
        assert outcome.history[-1].deferred_tool_use.id == "toolu_1"

    def test_failed_run_raises_with_its_errors(self):
        with pytest.raises(RuntimeError, match="API Error: 500"):
            _settle([], result(is_error=True, errors=["API Error: 500"]))


class TestResumeRun:
    async def resume(self, approved: bool) -> dict:
        """Resume a paused run, and return the hook's decision on its pending call."""
        client = MagicMock(spec=ClaudeSDKClient)
        client.__aenter__.return_value = client

        async def messages():
            yield result()

        client.receive_messages.return_value = messages()
        deps = AgentDeps(client=Mock(), session=CodeChannelSession(channel_id="C_CODE"))
        with patch("agent.agent.ClaudeSDKClient", return_value=client) as connect:
            await resume_run(PausedRun(history=[deferred()]), approved, deps)

        options = connect.call_args.args[0]
        assert options.resume == "session-1"
        # Resuming sends no prompt, so the CLI picks the deferred call back up.
        client.query.assert_not_called()
        hook = options.hooks["PreToolUse"][0].hooks[0]
        data = PreToolUseHookInput(
            session_id="session-1",
            transcript_path="",
            cwd="",
            hook_event_name="PreToolUse",
            tool_name="mcp__coding-agent__run_command",
            tool_input={"command": "rm -rf build"},
            tool_use_id="toolu_1",
        )
        output = await hook(data, "toolu_1", HookContext(signal=None))
        return output["hookSpecificOutput"]

    async def test_approving_approves_the_pending_item(self):
        decision = await self.resume(approved=True)

        assert decision["permissionDecision"] == "allow"

    async def test_denying_rejects_the_pending_item(self):
        decision = await self.resume(approved=False)

        assert decision["permissionDecision"] == "deny"
        assert "denied" in decision["permissionDecisionReason"]


class TestOutOfTurns:
    def test_running_out_of_turns_ends_with_a_message_in_history(self):
        out_of_turns = result(subtype="error_max_turns", is_error=True, result="")

        outcome = _settle([], out_of_turns)

        assert str(MAX_TURNS) in outcome.final_output
        assert outcome.history == [out_of_turns]
