from claude_agent_sdk import tool
from slack_sdk.errors import SlackApiError

from agent.sessions import current_deps
from agent.tools import tool_result

DESCRIPTION = """\
Read the Plan tab and any open comments people left on it.

Call this at the start of each turn once a plan exists, and fold the \
feedback into your work and your next `write_plan`.\
"""


@tool("read_plan", DESCRIPTION, {"type": "object", "properties": {}})
async def read_plan(_args: dict) -> dict:
    deps = current_deps.get()
    canvas_id = deps.session.plan_canvas_id
    if not canvas_id:
        return tool_result("No plan yet — call write_plan to create one.")

    try:
        response = await deps.client.agents_conversations_getCanvas(
            channel=deps.channel_id,
            canvas_id=canvas_id,
            include_resolved=False,
        )
    except SlackApiError as e:
        return tool_result(f"Could not read the plan: {e.response['error']}")

    parts = [f"Plan:\n{response.get('content', '')}"]
    for comment in response.get("comments", []):
        replies = "".join(
            f"\n    ↳ <@{r['user_id']}>: {r['text']}"
            for r in comment.get("replies", [])
        )
        parts.append(
            f'- On "{comment.get("quoted_text", "")}", <@{comment["user_id"]}> said: '
            f"{comment['text']}{replies}"
        )
    if len(parts) == 1:
        parts.append("No open comments.")
    return tool_result("\n".join(parts))
