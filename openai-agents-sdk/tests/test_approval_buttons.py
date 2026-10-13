from unittest.mock import Mock, patch

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, session_store
from agent.agent import RunOutcome
from agent.approvals import pending_store
from listeners.actions.approval_buttons import handle_approval_buttons
from listeners.events.message import handle_message


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

    def send(self, text: str, outcome: RunOutcome, message_ts: str = "8.8"):
        """Send a message in C_CODE whose turn ends with `outcome`."""
        self.client.chat_postMessage.return_value = {"ts": message_ts}
        with patch("agent.turns.start_run", return_value=outcome):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "5.5", "text": text},
            )

    def pause_on(self, command: str, message_ts: str) -> Mock:
        """Run a turn in C_CODE that pauses on `command`, posting buttons at `message_ts`."""
        paused = Mock()
        self.send(
            f"run {command}",
            RunOutcome(paused=paused, command=command, history=self.history),
            message_ts,
        )
        return paused

    def click(self, value: str, message_ts: str) -> Mock:
        with patch(
            "agent.turns.resume_run",
            return_value=RunOutcome(final_output="Ran it.", history=self.history),
        ) as resume_run:
            handle_approval_buttons(
                ack=Mock(),
                action={"value": value},
                body={"message": {"ts": message_ts}},
                context=self.context,
                client=self.client,
            )
        return resume_run

    def test_approving_resumes_the_paused_run(self):
        paused = self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("approve", "9.1")

        assert resume_run.call_args.args[:2] == (paused, True)
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Approved" in update["text"]
        assert "rm -rf build" in update["text"]

    def test_denying_resumes_the_paused_run_with_a_rejection(self):
        paused = self.pause_on("rm -rf build", "9.1")

        resume_run = self.click("deny", "9.1")

        assert resume_run.call_args.args[:2] == (paused, False)
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

    def test_a_newer_message_retires_the_pending_approval(self):
        self.pause_on("rm -rf build", "9.1")
        newer = [{"role": "assistant", "content": "Newer."}]

        self.send("never mind", RunOutcome(final_output="Newer.", history=newer))

        # The buttons say the command was skipped, and a late click resumes nothing.
        skipped = self.client.chat_update.call_args.kwargs
        assert skipped["ts"] == "9.1"
        assert "Skipped" in skipped["text"]
        resume_run = self.click("approve", "9.1")
        resume_run.assert_not_called()
        assert session_store.get("C_CODE").history == newer

    def test_a_failed_resume_leaves_processing(self):
        self.pause_on("rm -rf build", "9.1")

        with patch("agent.turns.resume_run", side_effect=RuntimeError("boom")):
            handle_approval_buttons(
                ack=Mock(),
                action={"value": "approve"},
                body={"message": {"ts": "9.1"}},
                context=self.context,
                client=self.client,
            )

        assert "boom" in self.client.chat_postMessage.call_args.kwargs["text"]
        self.client.agents_sessions_setStatus.assert_called_with(
            channel_id="C_CODE", status="active"
        )
