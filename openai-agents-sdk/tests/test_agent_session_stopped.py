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

    def stop(self):
        handle_agent_session_stopped(
            client=self.client,
            context=self.context,
            event={"channel": "C_CODE", "streaming_message_ts": []},
            logger=test_logger,
        )

    def test_stop_confirms_and_leaves_processing(self):
        self.stop()

        assert self.session.stopped is True
        self.client.chat_postMessage.assert_called_once()
        assert self.client.chat_postMessage.call_args.kwargs["channel"] == "C_CODE"
        assert "Stopped" in self.client.chat_postMessage.call_args.kwargs["text"]
        self.client.agents_sessions_setStatus.assert_called_once_with(
            channel_id="C_CODE", status="active"
        )

    def test_stop_drops_the_pending_approval_and_its_buttons(self):
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

        self.stop()

        assert pending_store.pop("C_CODE", "9.1") is None
        update = self.client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Stopped before running" in update["text"]
        assert "rm -rf build" in update["text"]

    def test_stopped_turn_posts_nothing_more(self):
        def stop_mid_run(_input, _deps):
            self.stop()
            return RunOutcome(final_output="Done.", history=[])

        with patch("agent.agent.start_run", side_effect=stop_mid_run):
            handle_message(
                client=self.client,
                context=self.context,
                event={"ts": "4.4", "text": "keep going"},
                logger=test_logger,
            )

        # Only the stop confirmation is posted, not the turn's "Done.".
        posts = [c.kwargs["text"] for c in self.client.chat_postMessage.call_args_list]
        assert len(posts) == 1
        assert "Stopped" in posts[0]
        statuses = [
            c.kwargs["status"]
            for c in self.client.agents_sessions_setStatus.call_args_list
        ]
        assert statuses == ["processing", "active"]
