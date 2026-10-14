"""The session's working directory: running commands in it and keeping file access inside it."""

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

# Environment variables kept from the app's environment are everything except
# the app's own tokens and anything that looks like a credential, so a command
# from the repository can't read them.
SECRET_PREFIXES = ("OPENAI_", "SLACK_")
SECRET_MARKERS = ("API_KEY", "CREDENTIAL", "PASSWORD", "PRIVATE_KEY", "SECRET", "TOKEN")

# git never waits on a prompt or an editor, since nobody can answer one.
GIT_DEFAULTS = {
    "GIT_EDITOR": "true",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "PAGER": "cat",
}


@dataclass
class Output:
    returncode: int
    stdout: str
    stderr: str


def command_env() -> dict[str, str]:
    """The environment commands run with: the app's, minus its secrets."""
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(SECRET_PREFIXES)
        and not any(marker in name.upper() for marker in SECRET_MARKERS)
    }
    return {**env, **GIT_DEFAULTS}


async def _communicate(process, timeout: float) -> Output:
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    return Output(
        returncode=process.returncode,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


async def run_shell(command: str, *, cwd: str, timeout: float) -> Output:
    """Run a shell command line in `cwd`. Raises asyncio.TimeoutError past `timeout` seconds."""
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        env=command_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate(process, timeout)


async def run_git(*args: str, cwd: str, timeout: float = 60) -> Output:
    """Run git with `args` in `cwd`, without a shell."""
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=cwd,
        env=command_env(),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    return await _communicate(process, timeout)


def resolve_path(workdir: str, path: str, *, writing: bool = False) -> Path | None:
    """The absolute path for `path` inside `workdir`, or None if it's outside.

    Writes into `.git` are refused too: its config and hooks decide what git
    runs, and git commands like `git commit` run without asking.
    """
    root = Path(workdir).resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        return None
    if writing and _in_git_dir(root, target):
        return None
    return target


def _in_git_dir(root: Path, target: Path) -> bool:
    """Whether `target` is in a `.git` directory, however its name is written.

    A case-insensitive filesystem, like macOS's default, treats `.GIT` as `.git`,
    and Windows ignores trailing dots and spaces in names.
    """
    if any(
        part.casefold().rstrip(". ") == ".git"
        for part in target.relative_to(root).parts
    ):
        return True
    git_dir = root / ".git"
    if not git_dir.exists():
        return False
    # Catch any other name that leads to the same directory.
    return any(
        os.path.samefile(parent, git_dir)
        for parent in (target, *target.parents)
        if parent.is_relative_to(root) and parent.exists()
    )


def clip(text: str, limit: int) -> str:
    """Shorten `text` to about `limit` characters, keeping its start and its end.

    The end of command output usually matters most, like a test run's failures
    and summary, so it gets most of the room.
    """
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    cut = len(text) - head - tail
    return f"{text[:head]}\n… {cut} characters cut …\n{text[-tail:]}"
