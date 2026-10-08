from unittest.mock import Mock

from slack_bolt import BoltContext

from agent import CodeChannelSession, session_store
from agent.approvals import PendingApproval, pending_store
from listeners.events.channel_archive import handle_channel_archive


class TestChannelArchive:
    def setup_method(self):
        self.context = Mock(BoltContext)
        self.context.channel_id = "C_CODE"

    def teardown_method(self):
        session_store.discard("C_CODE")
        pending_store.discard("C_CODE")

    def test_archiving_from_slack_forgets_the_session(self, tmp_path):
        workdir = tmp_path / "clone"
        workdir.mkdir()
        session_store.put(CodeChannelSession(channel_id="C_CODE", workdir=str(workdir)))
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

        handle_channel_archive(context=self.context, event={"channel": "C_CODE"})

        assert session_store.get("C_CODE") is None
        assert pending_store.pop("C_CODE", "9.1") is None
        assert not workdir.exists()
