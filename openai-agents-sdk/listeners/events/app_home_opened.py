from slack_bolt import BoltContext
from slack_sdk import WebClient
from slack_sdk.models.blocks import MarkdownTextObject, SectionBlock
from slack_sdk.models.views import View


def handle_app_home_opened(client: WebClient, context: BoltContext, event: dict):
    """Publish a short Home tab that explains how to start a task.

    Under agent_view this event also fires for the Messages tab, which this
    sample leaves alone since work happens in code channels.
    """
    if event.get("tab") != "home":
        return

    client.views_publish(
        user_id=context.user_id,
        view=View(
            type="home",
            blocks=[
                SectionBlock(
                    text=MarkdownTextObject(
                        text=(
                            "Mention me in a channel with a coding task and a repo. "
                            "I'll answer quick questions in the thread and create a "
                            "code channel for anything that takes more than one message."
                        ),
                    ),
                ),
            ],
        ),
    )
