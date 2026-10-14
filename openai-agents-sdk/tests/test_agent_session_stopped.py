from unittest.mock import Mock, patch

from agent.approvals import PendingApproval, pending_store
from agent.outcome import RunOutcome
from agent.store import CodeChannelSession, session_store
from listeners.events.agent_session_stopped import handle_agent_session_stopped
from listeners.events.message import handle_message


class TestAgentSessionStopped:
    async def stop(self, client, context):
        await handle_agent_session_stopped(
            client=client,
            context=context,
            event={"channel": "C_CODE", "streaming_message_ts": []},
        )

    async def send(self, client, context, text: str):
        await handle_message(
            client=client, context=context, event={"ts": "4.4", "text": text}
        )

    async def test_stop_confirms_and_leaves_processing(self, client, context):
        session = CodeChannelSession(channel_id="C_CODE", inbox=["<@U1>: queued"])
        session_store.put(session)

        await self.stop(client, context)

        assert session.stopped is True
        assert session.inbox == []
        client.chat_postMessage.assert_called_once()
        assert client.chat_postMessage.call_args.kwargs["channel"] == "C_CODE"
        assert "Stopped" in client.chat_postMessage.call_args.kwargs["text"]
        client.agents_sessions_setStatus.assert_called_once_with(
            channel_id="C_CODE", status="active"
        )

    async def test_stop_drops_the_pending_approval_and_its_buttons(
        self, client, context
    ):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        pending_store.put(
            "C_CODE",
            PendingApproval(
                paused=Mock(), deps=Mock(), command="rm -rf build", message_ts="9.1"
            ),
        )

        await self.stop(client, context)

        assert pending_store.pop("C_CODE", "9.1") is None
        update = client.chat_update.call_args.kwargs
        assert update["ts"] == "9.1"
        assert "Stopped before running" in update["text"]
        assert "rm -rf build" in update["text"]

    async def test_stopped_turn_posts_nothing_more(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        async def stop_mid_run(_history, _text, _deps):
            await self.stop(client, context)
            return RunOutcome(final_output="Done.", history=[])

        with patch("agent.turns.start_run", side_effect=stop_mid_run):
            await self.send(client, context, "keep going")

        # Only the stop confirmation is posted, not the turn's "Done.".
        posts = [c.kwargs["text"] for c in client.chat_postMessage.call_args_list]
        assert len(posts) == 1
        assert "Stopped" in posts[0]
        statuses = [
            c.kwargs["status"] for c in client.agents_sessions_setStatus.call_args_list
        ]
        # The stop sets active, and the stopped turn sets it again in case its
        # processing landed after the stop.
        assert statuses == ["processing", "active", "active"]

    async def test_a_message_after_the_stop_picks_back_up(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))
        texts = []

        async def run(_history, text, _deps):
            texts.append(text)
            if len(texts) == 1:
                await self.stop(client, context)
                await self.send(client, context, "try this instead")
            return RunOutcome(final_output="Done.", history=[])

        with patch("agent.turns.start_run", side_effect=run):
            await self.send(client, context, "keep going")

        assert texts == ["<@U123>: keep going", "<@U123>: try this instead"]
        assert session_store.get("C_CODE").stopped is False
