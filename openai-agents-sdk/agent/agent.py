import json
import logging
import threading
from dataclasses import dataclass, field

from agents import (
    Agent,
    OpenAIProvider,
    RunConfig,
    Runner,
    RunState,
    ToolApprovalItem,
)
from openai import AsyncOpenAI
from slack_sdk import WebClient
from slack_sdk.models.blocks import (
    ActionsBlock,
    ButtonElement,
    MarkdownTextObject,
    SectionBlock,
)

from agent.approvals import PendingApproval, pending_store
from agent.deps import AgentDeps, RequestDeps
from agent.store import CodeChannelSession, session_store
from agent.tools import (
    archive_channel,
    clone_repo,
    create_code_channel,
    list_views,
    publish_diff,
    publish_html_view,
    read_plan,
    remove_view,
    rename_session,
    run_command,
    set_commands,
    set_context_bar,
    write_plan,
)

SYSTEM_PROMPT = """\
You are a coding agent working inside a Slack code channel — a dedicated channel \
spun up for one task, where you collaborate with a user like a teammate.

## HOW A CODE CHANNEL WORKS
- This whole channel is one working session with you. The user talks to you here \
directly; you don't need to be @-mentioned on every message.
- Your final reply each turn is posted as a top-level message in the channel.
- You have a temp working directory for this session. Use your tools to do real work.
- The channel has a context bar along the top and view tabs (a Plan, the code \
tab's diff, and HTML reports) that you keep current with your tools.
- Messages starting with `/` are slash commands you registered with `set_commands`.

## HOW TO WORK
1. Clone the repo the user names with `clone_repo`. Ask for a URL if they didn't give one.
2. Pin the repo to the context bar with `set_context_bar`, and register a few \
useful commands with `set_commands` (e.g. `run-tests`, `summarize`, `wrap-up`).
3. Take a quick look before editing. Read only the files the task needs.
4. For anything beyond a one-line fix, `write_plan` with the steps before you \
edit. At the start of later turns, `read_plan` and address any comments people \
left on it.
5. Create a branch, then make focused changes with `run_command`. Add the branch \
to the context bar.
6. Run the project's tests/build to check your work. Keep the context bar's CI \
item current (e.g. "Tests passing"). Use `publish_html_view` for a long report.
7. `publish_diff` so the user sees the change, then summarize what you did and why.
8. When the user says the work is done, `archive_channel` with a wrap-up summary.

Plans always go in the Plan tab with `write_plan`, never in a message. When the \
user asks for a plan, call `write_plan`, then reply with one line pointing to the \
Plan tab.

## STYLE
- Be concise and concrete. Say what you're about to do, do it, report the result.
- When you hit a decision that needs the user, ask — don't guess on ambiguous intent.
- Never claim tests pass without running them. Show the command output that proves it.
"""

REQUEST_PROMPT = """\
You are a coding agent in Slack. Someone mentioned you in a channel or thread. \
Decide whether to reply here or create a code channel for the work.

## DECIDING WHETHER TO CREATE A CODE CHANNEL
Whether a request becomes a code channel is your call, made from the request and \
the context around it. Don't make the user ask for one. Creating a channel is \
cheap and reversible, so the question isn't whether a task is important enough, \
it's whether the work will take more than one message to complete.

Call `create_code_channel` when the work will:
- take multiple steps or need back-and-forth with the requester
- create or modify code, run builds or tests, or open a pull request
- produce progress updates or long output that would crowd the thread
- be explicitly requested as a session, task, or working space

Reply here when the request is:
- answerable in a single message, such as a question, a lookup, a short \
explanation, or a quick review comment
- about the surrounding conversation rather than about making changes
- something the people in the thread will want to see without leaving it

When it's genuinely ambiguous, reply here and offer to go deeper in a code channel.

## AFTER CREATING A CHANNEL
Don't start the work or reply with a plan. The work continues in the new channel.
"""

logger = logging.getLogger(__name__)

# Model calls allowed per turn. Coding work reads several files before editing,
# so this is well above the SDK's default of 10.
MAX_TURNS = 50

request_agent = Agent[RequestDeps](
    name="Coding Agent",
    instructions=REQUEST_PROMPT,
    tools=[create_code_channel],
    model="gpt-6-luna",
)

agent = Agent[AgentDeps](
    name="Coding Agent",
    instructions=SYSTEM_PROMPT,
    tools=[
        clone_repo,
        run_command,
        publish_diff,
        set_context_bar,
        write_plan,
        read_plan,
        publish_html_view,
        list_views,
        remove_view,
        set_commands,
        rename_session,
        archive_channel,
    ],
    model="gpt-6.1-sol",
)


@dataclass
class RunOutcome:
    """The result of a (possibly interrupted) agent run.

    Exactly one of `final_output` or `pending` is set:
    - `final_output` — the run completed; this is the text to post.
    - `pending_state` + `pending_item` — the run paused on a command that needs
      approval. The listener posts Approve/Deny buttons and resumes later.
    """

    final_output: str | None = None
    pending_state: RunState | None = None
    pending_item: ToolApprovalItem | None = None
    # Always set — the conversation so far, persisted so the next turn has context.
    history: list = field(default_factory=list)

    @property
    def needs_approval(self) -> bool:
        return self.pending_item is not None


def _settle(result) -> RunOutcome:
    """Turn a RunResult into a RunOutcome, detecting a pending approval."""
    history = result.to_input_list()
    state = result.to_state()
    interruptions = state.get_interruptions()
    if interruptions:
        # The history ends with calls still waiting on approval. Give each one
        # an output so the history stays valid if the run is stopped or replaced
        # instead of resumed. A resumed run replaces this history with its own.
        history += [
            {
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": "Not run. The user didn't approve this command.",
            }
            for item in interruptions
        ]
        # One command at a time keeps the sample's approval UX simple.
        return RunOutcome(
            pending_state=state,
            pending_item=interruptions[0],
            history=history,
        )
    return RunOutcome(final_output=result.final_output, history=history)


_thread = threading.local()


def _run_config() -> RunConfig:
    """Give each thread its own OpenAI client.

    Bolt runs listeners on worker threads, and `Runner.run_sync` drives each run
    on that thread's own event loop. The SDK's default client is shared across
    the process, so a connection opened on one thread's loop breaks when another
    thread reuses it. A client per thread stays on its thread's loop.
    """
    if not hasattr(_thread, "provider"):
        _thread.provider = OpenAIProvider(openai_client=AsyncOpenAI())
    return RunConfig(model_provider=_thread.provider)


def answer_request(text: str, deps: RequestDeps) -> str | None:
    """Reply in place to a mention, or create a code channel for it via the tool."""
    result = Runner.run_sync(
        request_agent,
        input=text,
        context=deps,
        run_config=_run_config(),
    )
    return result.final_output


def start_run(input_items, deps: AgentDeps) -> RunOutcome:
    """Start an agent turn. May complete, or pause awaiting command approval."""
    result = Runner.run_sync(
        agent,
        input=input_items,
        context=deps,
        max_turns=MAX_TURNS,
        run_config=_run_config(),
    )
    return _settle(result)


def resume_run(state: RunState, deps: AgentDeps) -> RunOutcome:
    """Resume a paused run after its pending approval was approved or rejected."""
    result = Runner.run_sync(
        agent,
        state,
        context=deps,
        run_config=_run_config(),
    )
    return _settle(result)


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
        client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="processing",
        )
        deps = AgentDeps(client=client, session=session, user_id=user_id)
        input_items = session.history + [{"role": "user", "content": text}]
        outcome = start_run(input_items, deps)
        deliver_outcome(outcome=outcome, deps=deps)


def resume_turn(*, pending: PendingApproval) -> None:
    """Resume a run paused on a command approval and post the outcome."""
    session = pending.deps.session
    with session.turn_lock:
        pending.deps.client.agents_sessions_setStatus(
            channel_id=session.channel_id,
            status="processing",
        )
        outcome = resume_run(pending.state, pending.deps)
        deliver_outcome(outcome=outcome, deps=pending.deps)


def deliver_outcome(*, outcome: RunOutcome, deps: AgentDeps) -> None:
    """Post an agent run's outcome to the code channel.

    If the run paused for approval, park the state and post Approve/Deny
    buttons. Otherwise post the final message top-level (the code channel
    convention) and mark the session active again.
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
        # The SDK gives the tool call's arguments as a JSON string.
        arguments = json.loads(outcome.pending_item.arguments or "{}")
        command = arguments.get("command", "")
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
                            f"```{command}```"
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
                state=outcome.pending_state,
                approval_item=outcome.pending_item,
                deps=deps,
                command=command,
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
