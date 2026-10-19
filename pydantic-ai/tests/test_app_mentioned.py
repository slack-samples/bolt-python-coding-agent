from unittest.mock import patch

from agent.outcome import RunOutcome
from agent.sessions import CodeChannelSession, session_store
from agent.tools import create_code_channel
from listeners.events.app_mentioned import handle_app_mentioned
from tests.conftest import code_channel_info
from tests.test_tools import invoke


class TestAppMentioned:
    async def mention(self, client, context, text: str, **event):
        await handle_app_mentioned(
            client=client,
            context=context,
            event={"ts": "1.1", "text": f"<@UBOT> {text}", **event},
        )

    async def mention_in_origin(
        self, client, context, answer, text="fix the login test", **event
    ):
        context.channel_id = "C_ORIGIN"
        client.conversations_info.return_value = {"channel": {"properties": {}}}
        client.agents_conversations_create.return_value = {"channel_id": "C_CODE"}
        with (
            patch("agent.turns.run_request", side_effect=answer) as run_request,
            patch("agent.turns.start_run") as start_run,
        ):
            await self.mention(client, context, text, **event)
        return run_request, start_run

    async def test_mention_answered_in_place_opens_no_channel(self, client, context):
        _, start_run = await self.mention_in_origin(
            client,
            context,
            lambda _prompt, _deps: "It's a billing service.",
            text="what does billing do?",
        )

        client.agents_conversations_create.assert_not_called()
        start_run.assert_not_called()
        assert client.chat_postMessage.call_args.kwargs == {
            "channel": "C_ORIGIN",
            "thread_ts": "1.1",
            "markdown_text": "It's a billing service.",
        }

    async def test_mention_in_a_thread_gets_the_thread_so_far(self, client, context):
        client.conversations_replies.return_value = {
            "messages": [
                {"ts": "0.5", "user": "U9", "text": "the login test flakes on CI"},
                {"ts": "1.1", "user": "U123", "text": "<@UBOT> can you fix this?"},
            ]
        }

        run_request, _ = await self.mention_in_origin(
            client,
            context,
            lambda _p, _d: "On it.",
            text="can you fix this?",
            thread_ts="0.5",
        )

        prompt = run_request.call_args.args[0]
        assert "<@U9>: the login test flakes on CI" in prompt
        assert prompt.endswith("<@U123>: can you fix this?")
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == "0.5"

    async def test_creating_a_channel_leaves_the_first_turn_to_the_seeded_mention(
        self, client, context
    ):
        async def create(_prompt, deps):
            await invoke(create_code_channel, deps, title="Fix login test")

        _, start_run = await self.mention_in_origin(client, context, create)

        create_call = client.agents_conversations_create.call_args.kwargs
        assert create_call["origin_channel_id"] == "C_ORIGIN"
        assert create_call["origin_message_ts"] == "1.1"
        assert create_call["session_id"] == "C_ORIGIN-1.1"
        # Slack seeds the new channel with the request, and that mention runs the turn.
        start_run.assert_not_called()
        assert [c.kwargs for c in client.chat_postMessage.call_args_list] == [
            {
                "channel": "C_ORIGIN",
                "thread_ts": "1.1",
                "text": "On it! Follow along in <#C_CODE>.",
            }
        ]

    async def test_creating_a_channel_twice_points_to_it_once(self, client, context):
        async def create_twice(_prompt, deps):
            await invoke(create_code_channel, deps, title="Fix login test")
            await invoke(create_code_channel, deps, title="Fix the login test")

        await self.mention_in_origin(client, context, create_twice)

        sessions = [
            c.kwargs["session_id"]
            for c in client.agents_conversations_create.call_args_list
        ]
        assert sessions == ["C_ORIGIN-1.1", "C_ORIGIN-1.1"]
        assert client.chat_postMessage.call_count == 1

    async def test_empty_mention_explains_itself(self, client, context):
        context.channel_id = "C_ORIGIN"
        client.conversations_info.return_value = {"channel": {"properties": {}}}

        await handle_app_mentioned(
            client=client, context=context, event={"ts": "1.1", "text": "<@UBOT>"}
        )

        assert "Mention me" in client.chat_postMessage.call_args.kwargs["text"]

    async def test_failed_turn_in_a_code_channel_warns_top_level(self, client, context):
        session_store.put(CodeChannelSession(channel_id="C_CODE"))

        with patch("agent.turns.start_run", side_effect=RuntimeError("boom")):
            await self.mention(client, context, "keep going", ts="6.6")

        warning = client.chat_postMessage.call_args.kwargs
        assert warning["channel"] == "C_CODE"
        assert "thread_ts" not in warning
        assert "boom" in warning["text"]
        # The failed turn moves the session out of processing.
        client.agents_sessions_setStatus.assert_called_with(
            channel_id="C_CODE", status="active"
        )

    async def test_new_code_channel_starts_with_the_conversation_it_came_from(
        self, client, context
    ):
        client.conversations_info.return_value = code_channel_info("C_ORIGIN", "1.1")

        async def replies(channel, ts, limit):
            assert channel == "C_ORIGIN"
            if ts == "1.1":
                return {"messages": [{"ts": "1.1", "thread_ts": "0.5", "user": "U123"}]}
            return {
                "messages": [
                    {"ts": "0.5", "user": "U9", "text": "the login test flakes"},
                    {"ts": "1.1", "user": "U123", "text": "<@UBOT> fix this"},
                ]
            }

        client.conversations_replies.side_effect = replies

        with patch(
            "agent.turns.start_run",
            return_value=RunOutcome(final_output="Cloning.", history=["turn"]),
        ) as start_run:
            await self.mention(client, context, "fix this", ts="7.7")
            await self.mention(client, context, "and add a test", ts="7.8")

        first, second = (c.args[1] for c in start_run.call_args_list)
        assert first.startswith("This code channel was started from this conversation:")
        assert "<@U9>: the login test flakes" in first
        assert first.endswith("<@U123>: fix this")
        assert second == "<@U123>: and add a test"
