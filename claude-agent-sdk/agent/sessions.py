"""Code channel sessions: their state, the deps each agent run gets, and the store.

A code channel is one session, so state is keyed by the code channel's own
channel_id. Each entry tracks the temp working directory the agent cloned into,
the plan canvas attached to the channel, and the conversation history, so
follow-up turns in the channel resume the same context. A session is discarded
when its channel is archived.

The deps passed to each agent run live here too: `AgentDeps` for a turn in a
code channel, and `RequestDeps` for a request outside one. The Claude Agent SDK
calls a tool with only its arguments, so `agent/agent.py` sets the run's deps in
`current_deps` before each run starts, and the tools and the hooks in
`agent/guardrails.py` read them back.
"""

import asyncio
import shutil
from contextvars import ContextVar
from dataclasses import dataclass, field

from slack_sdk.web.async_client import AsyncWebClient


@dataclass
class CodeChannelSession:
    """Per-code-channel working state."""

    channel_id: str
    origin_channel_id: str | None = None
    origin_message_ts: str | None = None
    # The conversation the channel was started from, given to the first turn.
    origin_context: str | None = None
    workdir: str | None = None
    repo_url: str | None = None
    base_branch: str | None = None
    # The commit that was cloned, which the published diff compares against.
    base_commit: str | None = None
    plan_canvas_id: str | None = None
    history: list = field(default_factory=list)
    # Messages waiting for the next turn, each starting with who sent it.
    inbox: list[str] = field(default_factory=list)
    # Set by the native stop button, or when the session is discarded. Checked
    # before posting and before every tool call so a stopped session goes quiet;
    # cleared when the user starts a new turn.
    stopped: bool = False
    # Set once the channel is archived, by the agent or from Slack; nothing more
    # is posted after that.
    archived: bool = False
    # One turn at a time per channel, so turns don't race on history.
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


@dataclass
class AgentDeps:
    """Dependencies passed to the agent and its tools for one turn.

    In a code channel the agent works inside `session.workdir` (a temp clone)
    and drives the channel chrome through `client` (the code channel Web API
    methods).
    """

    client: AsyncWebClient
    session: CodeChannelSession

    @property
    def channel_id(self) -> str:
        return self.session.channel_id


@dataclass
class RequestDeps:
    """Dependencies passed to the agent answering a request outside a code channel.

    The agent either replies in place or calls `create_code_channel`, which sets
    `code_channel_id` so `answer_request` knows the work moved there.
    """

    client: AsyncWebClient
    channel_id: str
    message_ts: str
    # The thread to reply in, or None to reply top-level, as in a direct message.
    thread_ts: str | None
    code_channel_id: str | None = None


current_deps: ContextVar[AgentDeps | RequestDeps] = ContextVar("current_deps")


class CodeChannelSessionStore:
    """In-memory store of active code channel sessions."""

    def __init__(self) -> None:
        self._store: dict[str, CodeChannelSession] = {}

    def get(self, channel_id: str) -> CodeChannelSession | None:
        return self._store.get(channel_id)

    def put(self, session: CodeChannelSession) -> None:
        self._store[session.channel_id] = session

    def discard(self, channel_id: str) -> None:
        """Remove a session and clean up its working directory.

        The session is also marked archived and stopped, so a turn still running
        in it calls no more tools and doesn't put it back when it finishes.
        """
        session = self._store.pop(channel_id, None)
        if session is None:
            return
        session.archived = session.stopped = True
        if session.workdir:
            shutil.rmtree(session.workdir, ignore_errors=True)


session_store = CodeChannelSessionStore()
