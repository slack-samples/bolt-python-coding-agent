from unittest.mock import Mock, patch

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, session_store
from agent.agent import RunOutcome
from listeners.events.message import handle_message


class TestMessage:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.bot_user_id = "UBOT"
        self.context.user_id = "U123"
        self.context.channel_id = "C_CODE"
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

    def teardown_method(self):
        session_store.discard("C_CODE")

    def test_message_in_a_code_channel_runs_a_turn(self):
        with patch(
            "agent.turns.start_run",
            return_value=RunOutcome(final_output="Done.", history=[]),
        ) as start_run:
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "3.3", "text": "keep going"},
            )

        assert start_run.call_args.args[1] == "keep going"
        self.client.chat_postMessage.assert_called_once_with(
            channel="C_CODE", markdown_text="Done."
        )
        statuses = [
            c.kwargs["status"]
            for c in self.client.agents_sessions_setStatus.call_args_list
        ]
        assert statuses == ["processing", "active"]

    def test_message_with_a_mention_is_left_to_app_mention(self):
        with patch("agent.turns.start_run") as start_run:
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "3.3", "text": "<@UBOT> again"},
            )

        start_run.assert_not_called()
