from dataclasses import dataclass

from slack_sdk.web.async_client import AsyncWebClient

from .sessions import CodeChannelSession


@dataclass
class AgentDeps:
    """Dependencies passed to the agent and its tools for one turn.

    In a code channel the agent works inside `session.workdir` (a temp clone)
    and drives the channel chrome through `client` (the code channel Web API
    methods).
    """

    client: AsyncWebClient
    session: CodeChannelSession
    user_id: str

    @property
    def channel_id(self) -> str:
        return self.session.channel_id


@dataclass
class RequestDeps:
    """Dependencies passed to the agent answering a request outside a code channel.

    The agent either replies in place or calls `create_code_channel`, which sets
    `code_channel_id` so `answer_request` knows the work moved there.
    """

    client: AsyncWebClient
    user_id: str
    channel_id: str
    message_ts: str
    # The thread to reply in, or None to reply top-level, as in a direct message.
    thread_ts: str | None
    code_channel_id: str | None = None
