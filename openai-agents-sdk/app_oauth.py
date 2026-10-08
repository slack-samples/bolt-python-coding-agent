import logging
import os

from dotenv import load_dotenv
from slack_bolt import App, BoltResponse
from slack_bolt.oauth.callback_options import CallbackOptions, FailureArgs, SuccessArgs
from slack_bolt.oauth.oauth_settings import OAuthSettings
from slack_sdk import WebClient
from slack_sdk.oauth.installation_store import FileInstallationStore
from slack_sdk.oauth.state_store import FileOAuthStateStore

from listeners import register_listeners

load_dotenv(dotenv_path=".env", override=False)

logging.basicConfig(level=logging.DEBUG)


# Callback to run on successful installation
def success(args: SuccessArgs) -> BoltResponse:
    # Call default handler to return an HTTP response
    return args.default.success(args)
    # return BoltResponse(status=200, body="Installation successful!")


# Callback to run on failed installation
def failure(args: FailureArgs) -> BoltResponse:
    return args.default.failure(args)
    # return BoltResponse(status=args.suggested_status_code, body=args.reason)


# Initialization
app = App(
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    client=WebClient(
        base_url=os.environ.get("SLACK_API_URL", "https://slack.com/api"),
    ),
    installation_store=FileInstallationStore(),
    oauth_settings=OAuthSettings(
        client_id=os.environ.get("SLACK_CLIENT_ID"),
        client_secret=os.environ.get("SLACK_CLIENT_SECRET"),
        scopes=[
            "app_mentions:read",
            "assistant:write",
            "canvases:write",
            "channels:history",
            "channels:read",
            "chat:write",
            "code_channels:manage",
            "groups:history",
            "groups:read",
            "im:history",
            "im:read",
            "im:write",
            "mpim:history",
        ],
        user_scopes=[],
        redirect_uri=None,
        install_path="/slack/install",
        redirect_uri_path="/slack/oauth_redirect",
        state_store=FileOAuthStateStore(expiration_seconds=600),
        callback_options=CallbackOptions(success=success, failure=failure),
    ),
)

# Register Listeners
register_listeners(app)

# Start Bolt app
if __name__ == "__main__":
    app.start(3000)
