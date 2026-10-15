from unittest.mock import Mock

from agent.approvals import PendingApproval, pending_store
from agent.sessions import CodeChannelSession, session_store
from listeners.events.channel_archive import handle_channel_archive


class TestChannelArchive:
    async def test_archiving_from_slack_forgets_the_session(self, context, tmp_path):
        workdir = tmp_path / "clone"
        workdir.mkdir()
        session_store.put(CodeChannelSession(channel_id="C_CODE", workdir=str(workdir)))
        pending_store.put(
            "C_CODE",
            PendingApproval(
                paused=Mock(), deps=Mock(), command="rm -rf build", message_ts="9.1"
            ),
        )

        await handle_channel_archive(context=context, event={"channel": "C_CODE"})

        assert session_store.get("C_CODE") is None
        assert pending_store.pop("C_CODE", "9.1") is None
        assert not workdir.exists()
