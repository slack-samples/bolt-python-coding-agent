"""Command approvals for the coding agent.

`run_command` executes shell commands the model chooses. To keep a human in the
loop, the tool is marked `needs_approval` with the callable below:

- Commands whose first token is on the read/inspect/test ALLOWLIST run
  immediately (no friction for safe, common operations).
- Anything else pauses the agent run. The listener posts Approve / Deny buttons
  in the code channel, parks the paused run in `pending_store`, and resumes it
  once a human decides.

This is a deliberately simple, conservative default for a public sample. It is
NOT a security boundary: a shell is expressive (pipes, subshells, `&&`) and this
checks only the first token. Treat approval as the real gate, and only ever run
this against trusted, throwaway repositories. See the README security section.
"""

import shlex
import threading
from dataclasses import dataclass
from logging import getLogger

from agents import RunState, ToolApprovalItem

from agent.deps import AgentDeps

logger = getLogger(__name__)

# First tokens that are safe to run without asking. Read, inspect, build, test.
ALLOWLIST: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "grep",
        "rg",
        "find",
        "wc",
        "pwd",
        "tree",
        "git",  # git is broad; see the note below
        "python",
        "python3",
        "pip",
        "pytest",
        "node",
        "npm",
        "npx",
        "make",
        "go",
        "cargo",
    }
)

# git subcommands that mutate remotes/history — force approval even though `git`
# is allowlisted, so the model can `git status`/`git diff` freely but a
# `git push` still asks.
GIT_SUBCOMMANDS_NEEDING_APPROVAL: frozenset[str] = frozenset(
    {
        "push",
        "reset",
        "clean",
        "rebase",
        "config",
    }
)


async def run_command_needs_approval(_ctx, arguments: dict, _call_id: str) -> bool:
    """`needs_approval` hook for the run_command tool.

    The OpenAI Agents SDK calls this with the tool's arguments before running.
    Returning True pauses the run with a ToolApprovalItem the listener handles.
    """
    command = (arguments or {}).get("command", "")
    try:
        tokens = shlex.split(command)
    except ValueError:
        # Unparseable (e.g. unbalanced quotes) — be safe and require approval.
        tokens = []

    needs = (
        not tokens
        or tokens[0] not in ALLOWLIST
        or (
            tokens[0] == "git"
            and len(tokens) > 1
            and tokens[1] in GIT_SUBCOMMANDS_NEEDING_APPROVAL
        )
    )
    if needs:
        logger.info("run_command needs approval: %s", command)
    return needs


@dataclass
class PendingApproval:
    """A paused agent run and the approval message awaiting a human decision."""

    state: RunState  # held live since we run in one process
    approval_item: ToolApprovalItem
    deps: AgentDeps
    command: str
    message_ts: str  # the message with the Approve / Deny buttons


class PendingApprovalStore:
    """Thread-safe store of paused runs, one per code channel.

    A newer paused run in the same channel replaces the older one, so a click
    only resolves the run whose buttons it came from. State is held in-process
    (fine for a single-instance sample); a multi-instance deployment would
    persist `RunState.to_string()` to a shared store instead.
    """

    def __init__(self) -> None:
        self._store: dict[str, PendingApproval] = {}
        self._lock = threading.Lock()

    def put(self, channel_id: str, pending: PendingApproval) -> None:
        with self._lock:
            self._store[channel_id] = pending

    def pop(self, channel_id: str, message_ts: str) -> PendingApproval | None:
        """Take the paused run whose approval message is `message_ts`, if any."""
        with self._lock:
            pending = self._store.get(channel_id)
            if pending is None or pending.message_ts != message_ts:
                return None
            return self._store.pop(channel_id)

    def discard(self, channel_id: str) -> None:
        with self._lock:
            self._store.pop(channel_id, None)


pending_store = PendingApprovalStore()
