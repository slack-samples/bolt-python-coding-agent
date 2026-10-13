"""Command approvals for the coding agent.

`run_command` executes shell commands the model chooses. To keep a human in the
loop, `command_needs_approval` decides which commands pause for a decision:

- A command that only reads, such as `ls`, `grep`, or `git diff`, runs
  immediately.
- Anything else pauses the agent run. The listener posts Approve / Deny buttons
  in the code channel, parks the paused run in `pending_store`, and resumes it
  once a human decides.

Running the repository's own code, such as its tests, build, or package
installs, always asks, since a cloned repository is untrusted input. So does any
command with shell syntax like `&&`, `|`, `;`, `>`, or `$(...)`, which could
chain a second command behind a read-only one, and any path that leaves the
clone, like `/etc`, `~/.ssh`, or `../x`. Only ever run this against
trusted, throwaway repositories. See the README security section.
"""

import shlex
import threading
from dataclasses import dataclass
from typing import Any

from agent.deps import AgentDeps

# Programs that only read, so they run without asking.
READ_ONLY_COMMANDS: frozenset[str] = frozenset(
    {
        "cat",
        "find",
        "git",
        "grep",
        "head",
        "ls",
        "pwd",
        "rg",
        "tail",
        "tree",
        "wc",
    }
)

# git subcommands that only read. Any other subcommand, or an option before the
# subcommand like `git -c`, asks first.
READ_ONLY_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "blame",
        "diff",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
    }
)

# Options that make a read-only program run or write something, matched as a
# prefix so `-execdir` and `--pre=cmd` count too.
UNSAFE_OPTIONS: dict[str, tuple[str, ...]] = {
    "find": ("-delete", "-exec", "-fls", "-fprint", "-ok"),
    "git": ("--output",),
    "rg": ("--pre",),
    "tree": ("-o",),
}

# Characters the shell treats as syntax: chaining, pipes, redirects, and
# substitutions. Any of them asks first, even inside quotes, to stay simple.
SHELL_SYNTAX: frozenset[str] = frozenset(";&|<>$`()\n")


def _reads_outside_the_clone(arg: str) -> bool:
    """Whether an argument can point outside the working directory.

    That's a path from the root or home (`/etc`, `~/.ssh`) or one that climbs out
    (`../x`). An option carrying a path, like `--file=/etc/x` or `-f/etc/x`, asks
    whenever it has a `/`, to stay simple.
    """
    if arg.startswith("-"):
        return "/" in arg or "~" in arg
    return arg.startswith(("/", "~")) or ".." in arg.split("/")


def command_needs_approval(command: str) -> bool:
    """Whether a shell command needs a human to approve it before it runs."""
    if not command.strip() or any(char in SHELL_SYNTAX for char in command):
        return True
    try:
        program, *args = shlex.split(command)
    except ValueError:
        # Unparseable (e.g. unbalanced quotes) — be safe and require approval.
        return True

    if program not in READ_ONLY_COMMANDS:
        return True
    if program == "git" and (not args or args[0] not in READ_ONLY_GIT_SUBCOMMANDS):
        return True
    if any(_reads_outside_the_clone(arg) for arg in args):
        return True
    unsafe = UNSAFE_OPTIONS.get(program, ())
    return any(arg.startswith(unsafe) for arg in args)


@dataclass
class PendingApproval:
    """A paused agent run and the approval message awaiting a human decision."""

    # The framework's handle on the paused run, passed back to `resume_run`.
    paused: Any
    deps: AgentDeps
    command: str
    message_ts: str  # the message with the Approve / Deny buttons


class PendingApprovalStore:
    """Thread-safe store of paused runs, one per code channel.

    A newer paused run in the same channel replaces the older one, so a click
    only resolves the run whose buttons it came from. State is held in-process
    (fine for a single-instance sample); a multi-instance deployment would
    persist the paused run to a shared store instead.
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

    def discard(self, channel_id: str) -> PendingApproval | None:
        """Drop the channel's paused run, whatever its message, and return it."""
        with self._lock:
            return self._store.pop(channel_id, None)


pending_store = PendingApprovalStore()
