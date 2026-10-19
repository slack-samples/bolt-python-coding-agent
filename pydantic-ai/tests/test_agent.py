from unittest.mock import AsyncMock, Mock, patch

from pydantic_ai import DeferredToolRequests, ToolDenied
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.run import AgentRunResult
from pydantic_ai.usage import RunUsage

from agent.agent import MAX_TURNS, PausedRun, _out_of_turns, _settle, resume_run
from agent.sessions import AgentDeps, CodeChannelSession

HISTORY = [ModelResponse(parts=[TextPart(content="Done.")])]


def run_result(output) -> Mock:
    """An AgentRunResult whose methods match the real one's, so a wrong call fails."""
    result = Mock(spec=AgentRunResult)
    result.output = output
    result.usage = RunUsage(requests=2)
    result.all_messages.return_value = list(HISTORY)
    return result


def deps() -> AgentDeps:
    return AgentDeps(client=Mock(), session=CodeChannelSession(channel_id="C_CODE"))


class TestSettle:
    def test_completed_run_keeps_its_history(self):
        outcome = _settle(run_result("Done."), deps())

        assert outcome.final_output == "Done."
        assert outcome.needs_approval is False
        assert outcome.history == HISTORY

    def test_paused_run_answers_the_pending_call_in_its_history(self):
        call = ToolCallPart(
            tool_name="run_command",
            args={"command": "rm -rf build"},
            tool_call_id="call_1",
        )
        requests = DeferredToolRequests(approvals=[call])

        outcome = _settle(run_result(requests), deps())

        assert outcome.paused.requests is requests
        assert outcome.paused.messages == HISTORY
        assert outcome.paused.usage.requests == 2
        assert outcome.command == "rm -rf build"
        # A stopped or replaced run leaves this history behind, and every call
        # in it needs a return or the next request fails.
        answered = outcome.history[-1]
        assert outcome.history[:-1] == HISTORY
        assert isinstance(answered, ModelRequest)
        assert answered.parts[0].tool_call_id == "call_1"
        assert (
            answered.parts[0].content
            == "Not run. The user didn't approve this command."
        )

    def test_archived_run_has_nothing_to_post(self):
        session_deps = deps()
        session_deps.session.archived = True

        outcome = _settle(run_result("Posted the summary."), session_deps)

        assert outcome.final_output is None
        assert outcome.needs_approval is False


class TestResumeRun:
    async def resume(self, approved: bool, *calls: ToolCallPart):
        paused = PausedRun(
            messages=list(HISTORY),
            requests=DeferredToolRequests(approvals=list(calls)),
            usage=RunUsage(requests=2),
        )
        with patch("agent.agent._run", new=AsyncMock()) as run:
            await resume_run(paused, approved, deps())
        return run.call_args.kwargs

    def command(self, tool_call_id: str) -> ToolCallPart:
        return ToolCallPart(
            tool_name="run_command",
            args={"command": "pytest"},
            tool_call_id=tool_call_id,
        )

    async def test_approving_approves_the_pending_item(self):
        kwargs = await self.resume(True, self.command("call_1"))

        assert kwargs["deferred_tool_results"].approvals == {"call_1": True}
        assert kwargs["message_history"] == HISTORY
        assert kwargs["usage"].requests == 2

    async def test_denying_rejects_the_pending_item(self):
        kwargs = await self.resume(False, self.command("call_1"))

        denied = kwargs["deferred_tool_results"].approvals["call_1"]
        assert isinstance(denied, ToolDenied)
        assert "denied" in denied.message

    async def test_other_commands_from_the_same_step_are_not_run(self):
        kwargs = await self.resume(True, self.command("call_1"), self.command("call_2"))

        approvals = kwargs["deferred_tool_results"].approvals
        assert approvals["call_1"] is True
        assert isinstance(approvals["call_2"], ToolDenied)
        assert "Not run" in approvals["call_2"].message


class TestOutOfTurns:
    def test_running_out_of_turns_ends_with_a_message_in_history(self):
        earlier = [
            ModelRequest(
                parts=[ToolReturnPart(tool_name="pwd", content="/", tool_call_id="c")]
            )
        ]

        outcome = _out_of_turns(earlier)

        assert str(MAX_TURNS) in outcome.final_output
        assert outcome.history[:-1] == earlier
        assert outcome.history[-1].parts[0].content == outcome.final_output
