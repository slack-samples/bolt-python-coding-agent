from slack_bolt import App

from .approval_buttons import handle_approval_buttons


def register(app: App):
    app.action("approve_command")(handle_approval_buttons)
    app.action("deny_command")(handle_approval_buttons)
