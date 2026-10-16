from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.sessions import RequestDeps


@function_tool
async def create_code_channel(
    wrapper: RunContextWrapper[RequestDeps], title: str
) -> str:
    """Create a code channel for this request, where the coding work happens.

    Call it when the work will take more than one message: changing code, running
    builds or tests, opening a pull request, or iterating with the requester. The
    work continues in the new channel, so don't start it here.

    Args:
        title: A short, descriptive title for the task, such as `Fix flaky login test`.
    """
    deps = wrapper.context
    try:
        # The session_id comes from the triggering message, not the model, so a
        # repeated call or a retried event reuses the same channel.
        created = await deps.client.agents_conversations_create(
            name=title[:80],
            session_id=f"{deps.channel_id}-{deps.message_ts}",
            origin_channel_id=deps.channel_id,
            origin_message_ts=deps.message_ts,
        )
    except SlackApiError as e:
        return f"Could not create a code channel: {e.response['error']}"

    channel_id = created["channel_id"]
    # Slack seeds the channel with the request, mention included, and that
    # mention starts the session there.
    if deps.code_channel_id is None:
        await deps.client.chat_postMessage(
            channel=deps.channel_id,
            thread_ts=deps.thread_ts,
            text=f"On it! Follow along in <#{channel_id}>.",
        )
    deps.code_channel_id = channel_id
    return f"Created <#{channel_id}>. The work continues there."
