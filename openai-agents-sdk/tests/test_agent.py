import json
from unittest.mock import Mock, patch

from agents import RunResult, RunState, ToolApprovalItem

from agent.agent import MAX_TURNS, PausedRun, _out_of_turns, _settle, resume_run


def run_result(interruptions: list) -> Mock:
    """A RunResult whose methods match the real SDK's, so a wrong call fails."""
    state = Mock(spec=RunState)
    state.get_interruptions.return_value = interruptions
    result = Mock(spec=RunResult)
    result.final_output = "Done."
    result.to_state.return_value = state
    result.to_input_list.return_value = [{"role": "assistant", "content": "Done."}]
    return result


class TestSettle:
    def test_completed_run_keeps_its_history(self):
        outcome = _settle(run_result([]))

        assert outcome.final_output == "Done."
        assert outcome.needs_approval is False
        assert outcome.history == [{"role": "assistant", "content": "Done."}]

    def test_paused_run_answers_the_pending_call_in_its_history(self):
        item = Mock(
            spec=ToolApprovalItem,
            call_id="call_1",
            arguments=json.dumps({"command": "rm -rf build"}),
        )
        result = run_result([item])

        outcome = _settle(result)

        assert outcome.paused.item is item
        assert outcome.paused.state is result.to_state.return_value
        assert outcome.command == "rm -rf build"
        # A stopped or replaced run leaves this history behind, and every call
        # in it needs an output or the next request fails.
        assert outcome.history == [
            {"role": "assistant", "content": "Done."},
            {
                "type": "function_call_output",
                "call_id": "call_1",
                "output": "Not run. The user didn't approve this command.",
            },
        ]


class TestResumeRun:
    def resume(self, approved: bool) -> PausedRun:
        paused = PausedRun(state=Mock(spec=RunState), item=Mock(spec=ToolApprovalItem))
        paused.state.get_interruptions.return_value = []
        with patch("agent.agent.Runner.run_sync", return_value=run_result([])):
            resume_run(paused, approved, Mock())
        return paused

    def test_approving_approves_the_pending_item(self):
        paused = self.resume(approved=True)

        paused.state.approve.assert_called_once_with(paused.item)
        paused.state.reject.assert_not_called()

    def test_denying_rejects_the_pending_item(self):
        paused = self.resume(approved=False)

        paused.state.reject.assert_called_once()
        assert paused.state.reject.call_args.args == (paused.item,)
        paused.state.approve.assert_not_called()


class TestOutOfTurns:
    def test_running_out_of_turns_ends_with_a_message_in_history(self):
        result = _out_of_turns(Mock())

        assert str(MAX_TURNS) in result.final_output
        assert result.include_in_history is True
