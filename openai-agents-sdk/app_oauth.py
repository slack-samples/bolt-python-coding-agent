import logging
import os

from dotenv import load_dotenv
from slack_bolt import BoltResponse
from slack_bolt.async_app import AsyncApp
from slack_bolt.oauth.async_callback_options import (
    AsyncCallbackOptions,
    AsyncFailureArgs,
    AsyncSuccessArgs,
)
from slack_bolt.oauth.async_oauth_settings import AsyncOAuthSettings
from slack_sdk.oauth.installation_store import FileInstallationStore
from slack_sdk.oauth.state_store import FileOAuthStateStore
from slack_sdk.web.async_client import AsyncWebClient

from listeners import register_listeners

load_dotenv(dotenv_path=".env", override=False)

logging.basicConfig(level=logging.DEBUG)


# Callback to run on successful installation
async def success(args: AsyncSuccessArgs) -> BoltResponse:
    # Call default handler to return an HTTP response
    return await args.default.success(args)
    # return BoltResponse(status=200, body="Installation successful!")


# Callback to run on failed installation
async def failure(args: AsyncFailureArgs) -> BoltResponse:
    return await args.default.failure(args)
    # return BoltResponse(status=args.suggested_status_code, body=args.reason)


# Initialization
app = AsyncApp(
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
    client=AsyncWebClient(
        base_url=os.environ.get("SLACK_API_URL", "https://slack.com/api"),
    ),
    installation_store=FileInstallationStore(),
    oauth_settings=AsyncOAuthSettings(
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
        callback_options=AsyncCallbackOptions(success=success, failure=failure),
    ),
)

# Register Listeners
register_listeners(app)

# Start Bolt app
if __name__ == "__main__":
    app.start(3000)
