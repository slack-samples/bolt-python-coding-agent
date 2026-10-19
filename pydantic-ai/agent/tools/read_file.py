from pydantic_ai import RunContext

from agent.sessions import AgentDeps
from agent.workspace import resolve_path

# Enough to read most source files whole, without one file crowding the turn.
MAX_CHARS = 20000


async def read_file(
    ctx: RunContext[AgentDeps],
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read a file from the cloned repository.

    Reads the whole file, or the lines from `start_line` to `end_line` for a
    large one. Long reads are cut short, so read big files in parts.

    Args:
        path: The file's path relative to the repository root, such as `src/app.py`.
        start_line: The first line to read, counting from 1, or omit it to start at the top.
        end_line: The last line to read, or omit it to read to the end.
    """
    session = ctx.deps.session
    if not session.workdir:
        return "No working directory yet — call clone_repo first."
    target = resolve_path(session.workdir, path)
    if target is None:
        return f"Can't read {path}: it's outside the repository."
    if not target.is_file():
        return f"No file at {path}."

    lines = target.read_text(errors="replace").splitlines()
    start = max(start_line or 1, 1)
    end = len(lines) if end_line is None else min(end_line, len(lines))
    content = "\n".join(lines[start - 1 : end])
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS]
        return (
            f"{path} (lines {start}–{end} of {len(lines)}, cut short at "
            f"{MAX_CHARS} characters — read the rest with a later start_line):\n{content}"
        )
    return f"{path} (lines {start}–{end} of {len(lines)}):\n{content}"
