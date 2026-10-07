import re

from slack_bolt import App

from .agent_command import handle_agent_command


def register(app: App):
    # Commands are registered per channel by the agent (set_commands), so match them all.
    app.command(re.compile(r"^/.+"))(handle_agent_command)
