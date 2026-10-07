"""In-memory store mapping a code channel to its working session.

A code channel is one session, so state is keyed by the code channel's own
channel_id. Each entry tracks the temp working directory the agent cloned into,
the plan canvas attached to the channel, and the OpenAI Agents conversation
history, so follow-up turns in the channel resume the same context. A session
is discarded when its channel is archived.
"""

import shutil
import threading
from dataclasses import dataclass, field


@dataclass
class CodeChannelSession:
    """Per-code-channel working state."""

    channel_id: str
    origin_channel_id: str | None = None
    origin_message_ts: str | None = None
    workdir: str | None = None
    repo_url: str | None = None
    base_branch: str | None = None
    plan_canvas_id: str | None = None
    history: list = field(default_factory=list)
    # Set by the native stop button. Checked before posting and between tool
    # calls so a stopped session goes quiet; cleared when the user starts a new turn.
    stopped: bool = False
    # Set once the agent archives the channel; nothing more is posted after that.
    archived: bool = False
    # One turn at a time per channel, so two quick messages don't race on history.
    turn_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class CodeChannelSessionStore:
    """Thread-safe in-memory store of active code channel sessions."""

    def __init__(self) -> None:
        self._store: dict[str, CodeChannelSession] = {}
        self._lock = threading.Lock()

    def get(self, channel_id: str) -> CodeChannelSession | None:
        with self._lock:
            return self._store.get(channel_id)

    def put(self, session: CodeChannelSession) -> None:
        with self._lock:
            self._store[session.channel_id] = session

    def discard(self, channel_id: str) -> None:
        """Remove a session and clean up its working directory."""
        with self._lock:
            session = self._store.pop(channel_id, None)
        if session is not None and session.workdir:
            shutil.rmtree(session.workdir, ignore_errors=True)


session_store = CodeChannelSessionStore()
