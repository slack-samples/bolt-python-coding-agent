import json
import logging
from unittest.mock import Mock, patch

from agents import ToolApprovalItem
from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, RunOutcome, session_store
from agent.approvals import pending_store
from listeners.actions.approval_buttons import handle_approval_buttons
from listeners.events.message import handle_message

test_logger = logging.getLogger(__name__)


class TestApprovalButtons:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.bot_user_id = "UBOT"
        self.context.user_id = "U123"
        self.context.channel_id = "C_CODE"
        self.history = [{"role": "assistant", "content": "Done."}]
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

    def teardown_method(self):
        session_store.discard("C_CODE")
        pending_store.discard("C_CODE")

    def pause_on(self, command: str, message_ts: str):
        """Run a turn in C_CODE that pauses on `command`, posting buttons at `message_ts`."""
        item = Mock(spec=ToolApprovalItem, arguments=json.dumps({"command": command}))
        self.client.chat_postMessage.return_value = {"ts": message_ts}
        with patch(
            "agent.agent.start_run",
            return_value=RunOutcome(
                pending_state=Mock(),
                pending_item=item,
                history=self.history,
            ),
        ):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "5.5", "text": f"run {command}"},
                logger=test_logger,
            )
        return item

    def click(self, value: str, message_ts: str):
        with patch(
            "agent.agent.resume_run",
            return_value=RunOutcome(final_output="Ran it.", history=self.history),
        ) as resume_run:
            handle_approval_buttons(
                ack=Mock(),
                action={"value": value},
                body={"message": {"ts": message_ts}},
                context=self.context,
                client=self.client,
                logger=test_logger,
            )
        return resume_run

    def test_approving_resumes_the_paused_run(self):
        self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("approve", "9.1")

        state = resume_run.call_args.args[0]
        state.approve.assert_called_once()
        state.reject.assert_not_called()
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Approved" in update["text"]
        assert "rm -rf build" in update["text"]

    def test_denying_resumes_the_paused_run_with_a_rejection(self):
        self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("deny", "9.1")

        state = resume_run.call_args.args[0]
        state.reject.assert_called_once()
        state.approve.assert_not_called()
        assert "Denied" in self.client.chat_update.call_args.kwargs["text"]

    def test_stale_approval_never_approves_a_newer_command(self):
        self.pause_on("rm -rf build", "9.1")
        self.pause_on("git push --force", "9.2")

        resume_run = self.click("approve", "9.1")

        resume_run.assert_not_called()
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "expired" in update["text"]
        assert pending_store.pop("C_CODE", "9.2").command == "git push --force"
