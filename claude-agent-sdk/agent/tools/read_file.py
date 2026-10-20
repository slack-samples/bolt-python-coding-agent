from claude_agent_sdk import tool

from agent.sessions import current_deps
from agent.tools import tool_result
from agent.workspace import resolve_path

# Enough to read most source files whole, without one file crowding the turn.
MAX_CHARS = 20000

DESCRIPTION = """\
Read a file from the cloned repository.

Reads the whole file, or the lines from `start_line` to `end_line` for a \
large one. Long reads are cut short, so read big files in parts.\
"""


@tool(
    "read_file",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file's path relative to the repository root, such as `src/app.py`.",
            },
            "start_line": {
                "type": "integer",
                "description": "The first line to read, counting from 1, or omit it to start at the top.",
            },
            "end_line": {
                "type": "integer",
                "description": "The last line to read, or omit it to read to the end.",
            },
        },
        "required": ["path"],
    },
)
async def read_file(args: dict) -> dict:
    path = args["path"]
    session = current_deps.get().session
    if not session.workdir:
        return tool_result("No working directory yet — call clone_repo first.")
    target = resolve_path(session.workdir, path)
    if target is None:
        return tool_result(f"Can't read {path}: it's outside the repository.")
    if not target.is_file():
        return tool_result(f"No file at {path}.")

    lines = target.read_text(errors="replace").splitlines()
    start = max(args.get("start_line") or 1, 1)
    end_line = args.get("end_line")
    end = len(lines) if end_line is None else min(end_line, len(lines))
    content = "\n".join(lines[start - 1 : end])
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS]
        return tool_result(
            f"{path} (lines {start}–{end} of {len(lines)}, cut short at "
            f"{MAX_CHARS} characters — read the rest with a later start_line):\n{content}"
        )
    return tool_result(f"{path} (lines {start}–{end} of {len(lines)}):\n{content}")
