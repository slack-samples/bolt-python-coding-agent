"""Turns in a code channel: run the agent, post the outcome, handle approvals and stops.

Listeners call these functions and never the agent framework directly. This file
doesn't import the framework either. It calls `start_run` and `resume_run` from
`agent/agent.py` and reads the `RunOutcome` they return, treating
`outcome.paused` as a handle it only passes back to `resume_run`.
"""

import logging

from slack_sdk import WebClient
from slack_sdk.models.blocks import (
    ActionsBlock,
    ButtonElement,
    MarkdownTextObject,
    SectionBlock,
)

from agent.agent import RunOutcome, resume_run, start_run
from agent.approvals import PendingApproval, pending_store
from agent.deps import AgentDeps
from agent.store import CodeChannelSession, session_store

logger = logging.getLogger(__name__)

EXPIRED = ":hourglass: This approval has expired — please ask me again."


def run_turn(
    *,
    client: WebClient,
    session: CodeChannelSession,
    text: str,
    user_id: str,
) -> None:
    """Run the agent on a new message in a code channel and post the outcome.

    Mentions, plain messages, and slash commands all funnel through here, so
    every turn sets the session status, runs the agent, and posts the same way.
    """
    with session.turn_lock:
        # A new message from the user restarts a session they stopped.
        session.stopped = False
        # A command still waiting on approval belongs to the old turn. Its history
        # already says it didn't run, so retire its buttons rather than let a late
        # click resume that older run over this one.
        replaced = pending_store.discard(session.channel_id)
        if replaced is not None:
            _close_message(
                client,
                session.channel_id,
                replaced.message_ts,
                f":fast_forward: *Skipped for a newer message:* ```{replaced.command}```",
            )
        deps = AgentDeps(client=client, session=session, user_id=user_id)
        try:
            client.agents_sessions_setStatus(
                channel_id=session.channel_id,
                status="processing",
            )
            outcome = start_run(session.history, text, deps)
            deliver_outcome(outcome=outcome, deps=deps)
        except Exception as e:
            logger.exception("Agent turn failed")
            _fail_turn(deps, e)


def resume_turn(
    *,
    client: WebClient,
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
        _close_message(client, channel_id, message_ts, EXPIRED)
        return

    with session.turn_lock:
        # Take the pending run inside the lock, so a newer turn that already
        # retired it wins and this click can't resume over it.
        pending = pending_store.pop(channel_id, message_ts)
        if pending is None:
            _close_message(client, channel_id, message_ts, EXPIRED)
            return
        if approved:
            text = f":white_check_mark: *Approved:* ```{pending.command}```"
        else:
            text = f":x: *Denied:* ```{pending.command}```"
        _close_message(client, channel_id, pending.message_ts, text)

        deps = pending.deps
        try:
            deps.client.agents_sessions_setStatus(
                channel_id=channel_id,
                status="processing",
            )
            outcome = resume_run(pending.paused, approved, deps)
            deliver_outcome(outcome=outcome, deps=deps)
        except Exception as e:
            logger.exception("Agent turn failed")
            _fail_turn(deps, e)


def stop_turn(*, client: WebClient, channel_id: str) -> None:
    """Handle the native stop button.

    Slack doesn't change the session status on a stop, so stop the work, clean
    up, confirm the stop, and move the session out of `processing` here.
    """
    # Stop in-progress work: the running turn sees this flag, calls no more
    # tools, and posts nothing when it finishes.
    session = session_store.get(channel_id)
    if session is not None:
        session.stopped = True

    # Clean up a command waiting on approval so its buttons can't resume it.
    pending = pending_store.discard(channel_id)
    if pending is not None:
        _close_message(
            client,
            channel_id,
            pending.message_ts,
            f":octagonal_sign: *Stopped before running:* ```{pending.command}```",
        )

    client.chat_postMessage(
        channel=channel_id,
        text="Stopped. Send a message to pick back up.",
    )
    client.agents_sessions_setStatus(
        channel_id=channel_id,
        status="active",
    )


def end_session(channel_id: str) -> None:
    """Forget a code channel and delete its working directory."""
    pending_store.discard(channel_id)
    session_store.discard(channel_id)


def deliver_outcome(*, outcome: RunOutcome, deps: AgentDeps) -> None:
    """Post an agent run's outcome to the code channel.

    If the run paused for approval, park it and post Approve/Deny buttons.
    Otherwise post the final message top-level (the code channel convention)
    and mark the session active again.
    """
    client = deps.client
    session = deps.session

    if session.archived:
        session_store.discard(session.channel_id)
        return
    # Persist conversation history so the next turn resumes with context.
    session.history = outcome.history
    session_store.put(session)
    # After the stop button, post nothing. The stop handler already confirmed
    # the stop and moved the session out of processing.
    if session.stopped:
        return

    if outcome.needs_approval:
        # The agent can't continue until someone decides, so the session is suspended.
        client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="suspended",
        )
        # The button value carries only the decision. The channel and this
        # message's ts identify which paused run to resume.
        posted = client.chat_postMessage(
            channel=session.channel_id,
            text="The agent needs approval to run a command.",
            blocks=[
                SectionBlock(
                    text=MarkdownTextObject(
                        text=(
                            ":lock: *The agent wants to run a command that needs your approval:*\n"
                            f"```{outcome.command}```"
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
        return

    text = outcome.final_output or "(the agent finished without a message)"
    # The model writes standard markdown, not Slack mrkdwn.
    client.chat_postMessage(channel=session.channel_id, markdown_text=text)
    client.agents_sessions_setStatus(
        channel_id=session.channel_id,
        status="active",
    )


def _fail_turn(deps: AgentDeps, error: Exception) -> None:
    """Report a turn that raised, and move the session out of `processing`.

    The session keeps the history from before this turn, so the next message
    starts from the last turn that finished.
    """
    session = deps.session
    if session.archived:
        session_store.discard(session.channel_id)
        return
    # The stop handler already confirmed the stop and set the status.
    if session.stopped:
        return
    try:
        deps.client.chat_postMessage(
            channel=session.channel_id,
            text=f":warning: Something went wrong ({error}). Send a message to try again.",
        )
        deps.client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="active",
        )
    except Exception:
        logger.exception("Failed to report the failed turn")


def _close_message(client: WebClient, channel_id: str, ts: str, text: str) -> None:
    """Replace a message's blocks with `text`, so its buttons can't be clicked again."""
    try:
        client.chat_update(
            channel=channel_id,
            ts=ts,
            text=text,
            blocks=[SectionBlock(text=MarkdownTextObject(text=text))],
        )
    except Exception:
        logger.exception("Failed to update the approval message")
