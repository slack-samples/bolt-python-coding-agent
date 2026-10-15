"""In-memory store mapping a code channel to its working session.

A code channel is one session, so state is keyed by the code channel's own
channel_id. Each entry tracks the temp working directory the agent cloned into,
the plan canvas attached to the channel, and the conversation history, so
follow-up turns in the channel resume the same context. A session is discarded
when its channel is archived.
"""

import asyncio
import shutil
from dataclasses import dataclass, field


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
    # Set by the native stop button. Checked before posting and before every
    # tool call so a stopped session goes quiet; cleared when the user starts a new turn.
    stopped: bool = False
    # Set once the agent archives the channel; nothing more is posted after that.
    archived: bool = False
    # One turn at a time per channel, so turns don't race on history.
    turn_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)


class CodeChannelSessionStore:
    """In-memory store of active code channel sessions."""

    def __init__(self) -> None:
        self._store: dict[str, CodeChannelSession] = {}

    def get(self, channel_id: str) -> CodeChannelSession | None:
        return self._store.get(channel_id)

    def put(self, session: CodeChannelSession) -> None:
        self._store[session.channel_id] = session

    def discard(self, channel_id: str) -> None:
        """Remove a session and clean up its working directory."""
        session = self._store.pop(channel_id, None)
        if session is not None and session.workdir:
            shutil.rmtree(session.workdir, ignore_errors=True)


session_store = CodeChannelSessionStore()
