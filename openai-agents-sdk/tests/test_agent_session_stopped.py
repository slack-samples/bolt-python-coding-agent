import logging
from unittest.mock import Mock, patch

from slack_bolt import BoltContext
from slack_sdk import WebClient

from agent import CodeChannelSession, RunOutcome, session_store
from agent.approvals import PendingApproval, pending_store
from listeners.events.agent_session_stopped import handle_agent_session_stopped
from listeners.events.message import handle_message

test_logger = logging.getLogger(__name__)


class TestAgentSessionStopped:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.bot_user_id = "UBOT"
        self.context.user_id = "U123"
        self.context.channel_id = "C_CODE"
        self.session = CodeChannelSession(channel_id="C_CODE")
        session_store.put(self.session)

    def teardown_method(self):
        session_store.discard("C_CODE")
        pending_store.discard("C_CODE")

    def test_stop_drops_the_pending_approval(self):
        pending_store.put(
            "C_CODE",
            PendingApproval(
                state=Mock(),
                approval_item=Mock(),
                deps=Mock(),
                command="rm -rf build",
                message_ts="9.1",
            ),
        )

        handle_agent_session_stopped(context=self.context, event={"channel": "C_CODE"})

        assert self.session.stopped is True
        assert pending_store.pop("C_CODE", "9.1") is None

    def test_stopped_session_posts_nothing(self):
        def stop_mid_run(_input, _deps):
            handle_agent_session_stopped(
                context=self.context, event={"channel": "C_CODE"}
            )
            return RunOutcome(final_output="Done.", history=[])

        with patch("agent.agent.start_run", side_effect=stop_mid_run):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "4.4", "text": "keep going"},
                logger=test_logger,
            )

        assert self.session.stopped is True
        self.client.chat_postMessage.assert_not_called()
        statuses = [
            c.kwargs["status"]
            for c in self.client.agents_sessions_setStatus.call_args_list
        ]
        assert statuses == ["processing"]
