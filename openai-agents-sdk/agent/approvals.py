"""Command approvals for the coding agent.

`run_command` runs programs the model chooses. To keep a human in the loop,
`command_needs_approval` decides which commands pause for a decision:

- A command that only reads, such as `ls`, `grep`, or `git diff`, runs
  immediately. So do local git changes that git can undo, such as `git add`,
  `git commit`, and `git switch -c`.
- Anything else pauses the agent run. `agent/turns.py` posts Approve / Deny
  buttons in the code channel, parks the paused run in `pending_store`, and
  resumes it once a human decides.

Running the repository's own code, such as its tests, build, or package
installs, always asks, since a cloned repository is untrusted input. So does any
path that leaves the clone, like `/etc`, `C:\\Windows`, or `../x`. Commands run
without a shell, and this splits a command into arguments the same way
`run_command` does, so what's checked here is exactly what runs: `&&`, `|`, or
`$(...)` can't chain a second command, they're only text. On Windows, `.cmd`
and `.bat` programs like `npm` are the exception, since Windows runs them
through `cmd.exe`, which does read that syntax. File edits don't go through
here: the `write_file` and `edit_file` tools only write inside the clone. Only
ever run this against trusted, throwaway repositories. See the README's Command
approvals section.
"""

import shlex
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

# git subcommands that only read, or only change the local clone in ways git
# can undo. Any other subcommand, or an option before the subcommand like
# `git -c`, asks first.
SAFE_GIT_SUBCOMMANDS: frozenset[str] = frozenset(
    {
        "add",
        "blame",
        "branch",
        "commit",
        "diff",
        "log",
        "ls-files",
        "rev-parse",
        "show",
        "status",
        "switch",
    }
)

# Options that make a safe program run something, write outside its own
# files, or throw away work, matched as a prefix so `-execdir` and `--pre=cmd`
# count too. For git that includes the forced `git branch -C`, `-D`, and `-M`,
# which also catches the harmless `git diff -C` and `-M`, to stay simple.
UNSAFE_OPTIONS: dict[str, tuple[str, ...]] = {
    "find": ("-delete", "-exec", "-fls", "-fprint", "-ok"),
    "git": ("--discard-changes", "--force", "--output", "-C", "-D", "-M", "-f"),
    "rg": ("--pre",),
    "tree": ("-o",),
}


def _reads_outside_the_clone(arg: str) -> bool:
    """Whether an argument can point outside the working directory.

    That's a path from the root or a drive (`/etc`, `C:/Windows`, `//server`) or
    one that climbs out (`../x`), with either kind of slash. An option carrying a
    path, like `--file=/etc/x` or `-f/etc/x`, asks whenever it has a slash, to
    stay simple.
    """
    path = arg.replace("\\", "/")
    if path.startswith("-"):
        return "/" in path
    has_drive = len(path) > 1 and path[1] == ":"
    return path.startswith("/") or has_drive or ".." in path.split("/")


def command_needs_approval(command: str) -> bool:
    """Whether a command needs a human to approve it before it runs."""
    try:
        program, *args = shlex.split(command)
    except ValueError:
        # Unparseable (e.g. unbalanced quotes) or empty — be safe and require approval.
        return True

    if program not in READ_ONLY_COMMANDS:
        return True
    if program == "git" and (not args or args[0] not in SAFE_GIT_SUBCOMMANDS):
        return True
    if any(_reads_outside_the_clone(arg) for arg in args):
        return True
    unsafe = UNSAFE_OPTIONS.get(program, ())
    return any(arg.startswith(unsafe) for arg in args)


@dataclass
class PendingApproval:
    """A paused agent run and the approval message awaiting a human decision."""

    # The handle on the paused run, passed back to `resume_run`.
    paused: Any
    deps: AgentDeps
    command: str
    message_ts: str  # the message with the Approve / Deny buttons


class PendingApprovalStore:
    """Paused runs, one per code channel.

    A newer paused run in the same channel replaces the older one, so a click
    only resolves the run whose buttons it came from. State is held in-process
    (fine for a single-instance sample); a multi-instance deployment would
    persist the paused run to a shared store instead.
    """

    def __init__(self) -> None:
        self._store: dict[str, PendingApproval] = {}

    def put(self, channel_id: str, pending: PendingApproval) -> None:
        self._store[channel_id] = pending

    def pop(self, channel_id: str, message_ts: str) -> PendingApproval | None:
        """Take the paused run whose approval message is `message_ts`, if any."""
        pending = self._store.get(channel_id)
        if pending is None or pending.message_ts != message_ts:
            return None
        return self._store.pop(channel_id)

    def discard(self, channel_id: str) -> PendingApproval | None:
        """Drop the channel's paused run, whatever its message, and return it."""
        return self._store.pop(channel_id, None)


pending_store = PendingApprovalStore()
