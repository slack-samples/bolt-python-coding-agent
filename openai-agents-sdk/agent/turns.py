"""Turns in Slack: answer requests, run code channel turns, and handle approvals and stops.

Listeners call these functions and never the agent framework directly. This file
doesn't import the framework either. It calls `run_request`, `start_run`, and
`resume_run` from `agent/agent.py`: `run_request` returns the reply text, and the
other two return a `RunOutcome`. It passes `outcome.paused` back to
`resume_run` without looking inside.
"""

import logging
from collections.abc import Awaitable, Callable
from functools import partial

from slack_sdk.errors import SlackApiError
from slack_sdk.models.blocks import (
    ActionsBlock,
    ButtonElement,
    MarkdownTextObject,
    SectionBlock,
)
from slack_sdk.web.async_client import AsyncWebClient

from agent.agent import resume_run, run_request, start_run
from agent.approvals import PendingApproval, pending_store
from agent.context import origin_context, recent_context, thread_context
from agent.deps import AgentDeps, RequestDeps
from agent.outcome import RunOutcome
from agent.sessions import CodeChannelSession, session_store
from agent.workspace import clip

logger = logging.getLogger(__name__)

EXPIRED = ":hourglass: This approval has expired — please ask me again."

# Channels known not to be code channels, so a message there isn't looked up again.
_other_channels: set[str] = set()


def _shown(command: str | None) -> str:
    """A command for a code block: short enough for a message, and unable to end the block early."""
    return clip((command or "").replace("```", "'''"), 2500)


async def _close_message(
    client: AsyncWebClient, channel_id: str, ts: str, text: str
) -> None:
    """Replace a message's blocks with `text`, so its buttons can't be clicked again."""
    try:
        await client.chat_update(
            channel=channel_id,
            ts=ts,
            text=text,
            blocks=[SectionBlock(text=MarkdownTextObject(text=text))],
        )
    except Exception:
        logger.exception("Failed to update the approval message")


async def _fail_turn(deps: AgentDeps, error: Exception) -> None:
    """Report a turn that raised, and move the session out of `processing`.

    The session keeps the history from before this turn, so the next message
    starts from the last turn that finished.
    """
    session = deps.session
    if session.archived:
        session_store.discard(session.channel_id)
        return
    try:
        # The stop handler already confirmed the stop, so only the status is left.
        if not session.stopped:
            await deps.client.chat_postMessage(
                channel=session.channel_id,
                text=f":warning: Something went wrong ({error}). Send a message to try again.",
            )
        await deps.client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="active",
        )
    except Exception:
        logger.exception("Failed to report the failed turn")


async def deliver_outcome(*, outcome: RunOutcome, deps: AgentDeps) -> bool:
    """Post an agent run's outcome to the code channel. Returns whether it paused.

    If the run paused for approval, park it and post Approve/Deny buttons.
    Otherwise post the final message top-level (the code channel convention)
    and mark the session active again.
    """
    client = deps.client
    session = deps.session

    if session.archived:
        session_store.discard(session.channel_id)
        return False
    # Persist conversation history so the next turn resumes with context.
    session.history = outcome.history
    session_store.put(session)
    # After the stop button, post nothing. The stop handler already confirmed
    # the stop, but this turn may have set `processing` after it, so set
    # `active` again.
    if session.stopped:
        await client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="active",
        )
        return False

    if outcome.needs_approval:
        # The agent can't continue until someone decides, so the session is suspended.
        await client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="suspended",
        )
        # The button value carries only the decision. The channel and this
        # message's ts identify which paused run to resume.
        posted = await client.chat_postMessage(
            channel=session.channel_id,
            text="The agent needs approval to run a command.",
            blocks=[
                SectionBlock(
                    text=MarkdownTextObject(
                        text=(
                            ":lock: *The agent wants to run a command that needs your approval:*\n"
                            f"```{_shown(outcome.command)}```"
                        ),
                    ),
                ),
                ActionsBlock(
                    elements=[
                        ButtonElement(
                            text="Approve",
                            style="primary",
                            action_id="approve_command",
                            value="approve",
                        ),
                        ButtonElement(
                            text="Deny",
                            style="danger",
                            action_id="deny_command",
                            value="deny",
                        ),
                    ],
                ),
            ],
        )
        pending_store.put(
            session.channel_id,
            PendingApproval(
                paused=outcome.paused,
                deps=deps,
                command=outcome.command,
                message_ts=posted["ts"],
            ),
        )
        return True

    text = outcome.final_output or "(the agent finished without a message)"
    # The model writes standard markdown, not Slack mrkdwn.
    await client.chat_postMessage(channel=session.channel_id, markdown_text=text)
    await client.agents_sessions_setStatus(
        channel_id=session.channel_id,
        status="active",
    )
    return False


async def _run(deps: AgentDeps, run: Callable[[], Awaitable[RunOutcome]]) -> bool:
    """Run one agent turn and post its outcome. Returns whether it paused on an approval."""
    try:
        await deps.client.agents_sessions_setStatus(
            channel_id=deps.channel_id,
            status="processing",
        )
        outcome = await run()
        return await deliver_outcome(outcome=outcome, deps=deps)
    except Exception as e:
        logger.exception("Agent turn failed")
        await _fail_turn(deps, e)
        return False


async def _run_inbox(
    client: AsyncWebClient, session: CodeChannelSession, user_id: str
) -> None:
    """Run turns until the inbox is empty or a turn pauses on an approval."""
    while session.inbox and not session.archived:
        # A stop clears the inbox, so anything here was sent after it and picks
        # the session back up.
        session.stopped = False
        messages, session.inbox = session.inbox, []
        text = "\n\n".join(messages)
        if session.origin_context and not session.history:
            text = (
                "This code channel was started from this conversation:\n"
                f"{session.origin_context}\n\n{text}"
            )
            session.origin_context = None

        deps = AgentDeps(client=client, session=session, user_id=user_id)
        paused = await _run(deps, partial(start_run, session.history, text, deps))
        if paused:
            return


async def answer_request(
    *,
    client: AsyncWebClient,
    channel_id: str,
    message_ts: str,
    thread_ts: str | None,
    text: str,
    user_id: str,
    in_dm: bool,
) -> None:
    """Reply to a mention or direct message outside a code channel, or create one for it.

    A mention in a channel is answered in its thread. A direct message is answered
    where it was sent. The agent gets the conversation before the request, from
    the thread or from the direct message, so it can follow along.
    """
    reply_ts = thread_ts or (None if in_dm else message_ts)
    if not text:
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=reply_ts,
            text="Mention me with a question or a coding task and a repo.",
        )
        return

    try:
        if thread_ts:
            earlier = await thread_context(
                client, channel_id, thread_ts, before_ts=message_ts
            )
        elif in_dm:
            earlier = await recent_context(client, channel_id, before_ts=message_ts)
        else:
            earlier = ""
        prompt = f"<@{user_id}>: {text}"
        if earlier:
            prompt = f"Earlier in this conversation:\n{earlier}\n\n{prompt}"

        deps = RequestDeps(
            client=client,
            user_id=user_id,
            channel_id=channel_id,
            message_ts=message_ts,
            thread_ts=reply_ts,
        )
        reply = await run_request(prompt, deps)
        # When the agent created a code channel, the work continues there.
        if deps.code_channel_id is None:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=reply_ts,
                markdown_text=reply or "(the agent finished without a message)",
            )
    except Exception as e:
        logger.exception("Failed to answer the request")
        await client.chat_postMessage(
            channel=channel_id,
            thread_ts=reply_ts,
            text=f":warning: Something went wrong ({e}).",
        )


async def find_session(
    client: AsyncWebClient, channel_id: str
) -> CodeChannelSession | None:
    """The session for a code channel, starting one if the app has no state for it yet.

    That's every new channel the agent creates, once its seeded request arrives,
    plus channels started from Slack's own UI or forgotten after a restart.
    `record_channel.record_type` is set on every code channel at creation, so
    it's the reliable way to recognize one. A new session gets the conversation
    the channel was started from, for its first turn.
    """
    session = session_store.get(channel_id)
    if session is not None or channel_id in _other_channels:
        return session
    try:
        channel = (await client.conversations_info(channel=channel_id))["channel"]
    except SlackApiError as e:
        logger.warning("Couldn't look up %s: %s", channel_id, e.response["error"])
        return None
    properties = channel.get("properties", {})
    if properties.get("record_channel", {}).get("record_type") != "agent_channel":
        _other_channels.add(channel_id)
        return None

    origin = properties.get("agent_session", {}).get("origin_link", {})
    session = CodeChannelSession(
        channel_id=channel_id,
        origin_channel_id=origin.get("channel_id"),
        origin_message_ts=origin.get("ts"),
    )
    if session.origin_channel_id and session.origin_message_ts:
        session.origin_context = (
            await origin_context(
                client, session.origin_channel_id, session.origin_message_ts
            )
            or None
        )
    # Another event may have started this session while the lookups ran.
    existing = session_store.get(channel_id)
    if existing is not None:
        return existing
    session_store.put(session)
    return session


async def run_turn(
    *,
    client: AsyncWebClient,
    session: CodeChannelSession,
    text: str,
    user_id: str,
) -> None:
    """Run a message or slash command in a code channel as a turn and post the outcome.

    Mentions, plain messages, and slash commands all funnel through here. A
    message that arrives while a turn runs waits in the session's inbox, and
    everything waiting runs together as the next turn.
    """
    session.inbox.append(f"<@{user_id}>: {text}")
    if session.turn_lock.locked():
        # The running turn takes this message when it finishes.
        return

    async with session.turn_lock:
        # A command still waiting on approval belongs to the old turn. Its history
        # already says it didn't run, so retire its buttons rather than let a late
        # click resume that older run over this one.
        replaced = pending_store.discard(session.channel_id)
        if replaced is not None:
            await _close_message(
                client,
                session.channel_id,
                replaced.message_ts,
                f":fast_forward: *Skipped for a newer message:* ```{_shown(replaced.command)}```",
            )
        await _run_inbox(client, session, user_id)


async def resume_turn(
    *,
    client: AsyncWebClient,
    channel_id: str,
    message_ts: str,
    approved: bool,
) -> None:
    """Resume the run paused on the approval message at `message_ts`, if it's current.

    The buttons are replaced with the decision, or a note that the approval
    expired when the run was stopped or replaced by a newer message.
    """
    session = session_store.get(channel_id)
    if session is None:
        await _close_message(client, channel_id, message_ts, EXPIRED)
        return

    async with session.turn_lock:
        # Take the pending run inside the lock, so a newer turn that already
        # retired it wins and this click can't resume over it.
        pending = pending_store.pop(channel_id, message_ts)
        if pending is None:
            await _close_message(client, channel_id, message_ts, EXPIRED)
            return
        decision = ":white_check_mark: *Approved:*" if approved else ":x: *Denied:*"
        await _close_message(
            client,
            channel_id,
            message_ts,
            f"{decision} ```{_shown(pending.command)}```",
        )

        deps = pending.deps
        paused = await _run(deps, partial(resume_run, pending.paused, approved, deps))
        # Messages sent while the command ran come next.
        if not paused:
            await _run_inbox(client, session, deps.user_id)


async def stop_turn(*, client: AsyncWebClient, channel_id: str) -> None:
    """Handle the native stop button.

    Slack doesn't change the session status on a stop, so stop the work, clean
    up, confirm the stop, and move the session out of `processing` here.
    """
    # Stop in-progress work: the running turn sees this flag, calls no more
    # tools, and posts nothing when it finishes. Messages waiting for the next
    # turn are dropped with it.
    session = session_store.get(channel_id)
    if session is not None:
        session.stopped = True
        session.inbox.clear()

    # Clean up a command waiting on approval so its buttons can't resume it.
    pending = pending_store.discard(channel_id)
    if pending is not None:
        await _close_message(
            client,
            channel_id,
            pending.message_ts,
            f":octagonal_sign: *Stopped before running:* ```{_shown(pending.command)}```",
        )

    await client.chat_postMessage(
        channel=channel_id,
        text="Stopped. Send a message to pick back up.",
    )
    await client.agents_sessions_setStatus(
        channel_id=channel_id,
        status="active",
    )


def end_session(channel_id: str) -> None:
    """Forget a code channel and delete its working directory."""
    pending_store.discard(channel_id)
    session_store.discard(channel_id)
