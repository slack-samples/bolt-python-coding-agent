from agents import function_tool
from agents.run_context import RunContextWrapper
from slack_sdk.errors import SlackApiError

from agent.deps import AgentDeps


@function_tool
def publish_html_view(
    wrapper: RunContextWrapper[AgentDeps],
    view_key: str,
    name: str,
    html: str,
) -> str:
    """Publish an HTML document as a tab in the code channel.

    Use it for rich output that reads better rendered than as a message, such as
    a test report or coverage summary. Calling it again with the same `view_key`
    updates that tab in place. A channel holds at most 5 views.

    Args:
        view_key: A stable key for this view, such as `reports/tests.html`.
        name: The short tab label shown in the channel, such as `Tests`.
        html: A full, self-contained HTML document with inline styles and no external scripts.
    """
    deps = wrapper.context
    try:
        response = deps.client.agents_conversations_setView(
            channel_id=deps.channel_id,
            type="html",
            view_key=view_key,
            name=name,
            content=html,
        )
        return f"Published the `{name}` tab (view_id {response['view_id']})."
    except SlackApiError as e:
        return f"Could not publish the view: {e.response['error']}"
