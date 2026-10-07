from unittest.mock import Mock

from agents import RunResult, RunState

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

    def test_paused_run_keeps_its_history_and_approval(self):
        item = Mock()
        result = run_result([item])

        outcome = _settle(result)

        assert outcome.pending_item is item
        assert outcome.pending_state is result.to_state.return_value
        assert outcome.history == [{"role": "assistant", "content": "Done."}]
