from slack_bolt import App

from .agent_session_stopped import handle_agent_session_stopped
from .app_home_opened import handle_app_home_opened
from .app_mentioned import handle_app_mentioned
from .channel_archive import handle_channel_archive
from .message import handle_message


def register(app: App):
    app.event("agent_session_stopped")(handle_agent_session_stopped)
    app.event("app_home_opened")(handle_app_home_opened)
    app.event("app_mention")(handle_app_mentioned)
    app.event("channel_archive")(handle_channel_archive)
    app.event("group_archive")(handle_channel_archive)
    app.event("message")(handle_message)
