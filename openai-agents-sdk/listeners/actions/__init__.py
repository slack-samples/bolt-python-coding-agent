from slack_bolt.async_app import AsyncApp

from .approval_buttons import handle_approval_buttons


def register(app: AsyncApp):
    app.action("approve_command")(handle_approval_buttons)
    app.action("deny_command")(handle_approval_buttons)
