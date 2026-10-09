from unittest.mock import Mock

from agents import RunResult, RunState, ToolApprovalItem

from agent.agent import _settle


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
        item = Mock(spec=ToolApprovalItem, call_id="call_1")
        result = run_result([item])

        outcome = _settle(result)

        assert outcome.pending_item is item
        assert outcome.pending_state is result.to_state.return_value
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
