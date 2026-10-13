from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps
from agent.guardrails import session_stopped


@function_tool(tool_input_guardrails=[session_stopped])
def read_plan(wrapper: RunContextWrapper[AgentDeps]) -> str:
    """Read the Plan tab and any open comments people left on it.

    Call this at the start of each turn once a plan exists, and fold the
    feedback into your work and your next `write_plan`.
    """
    deps = wrapper.context
    canvas_id = deps.session.plan_canvas_id
    if not canvas_id:
        return "No plan yet — call write_plan to create one."

    try:
        response = deps.client.agents_conversations_getCanvas(
            channel=deps.channel_id,
            canvas_id=canvas_id,
            include_resolved=False,
        )
    except SlackApiError as e:
        return f"Could not read the plan: {e.response['error']}"

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
    return "\n".join(parts)
