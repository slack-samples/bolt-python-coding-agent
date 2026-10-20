from claude_agent_sdk import tool

from agent.sessions import current_deps
from agent.tools import tool_result
from agent.workspace import resolve_path

DESCRIPTION = """\
Create a file in the cloned repository, or replace one with new content.

Use it for new files or full rewrites. To change part of an existing file, \
use `edit_file`. Files under `.git` can't be written.\
"""


@tool(
    "write_file",
    DESCRIPTION,
    {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "The file's path relative to the repository root, such as `src/app.py`.",
            },
            "content": {
                "type": "string",
                "description": "The complete new contents of the file.",
            },
        },
        "required": ["path", "content"],
    },
)
async def write_file(args: dict) -> dict:
    path, content = args["path"], args["content"]
    session = current_deps.get().session
    if not session.workdir:
        return tool_result("No working directory yet — call clone_repo first.")
    target = resolve_path(session.workdir, path, writing=True)
    if target is None:
        return tool_result(
            f"Can't write {path}: it's outside the repository or inside `.git`."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return tool_result(f"Wrote {path} ({len(content.splitlines())} lines).")
