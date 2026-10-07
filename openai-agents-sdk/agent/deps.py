from dataclasses import dataclass

from slack_sdk import WebClient

from .store import CodeChannelSession


@dataclass
class AgentDeps:
    """Dependencies passed to the agent and its tools for one turn.

    In a code channel the agent works inside `session.workdir` (a temp clone)
    and drives the channel chrome through `client` (the code channel Web API
    methods).
    """

    client: WebClient
    session: CodeChannelSession
    user_id: str

    @property
    def channel_id(self) -> str:
        return self.session.channel_id


@dataclass
class RequestDeps:
    """Dependencies passed to the agent answering a mention outside a code channel.

    The agent either replies in place or calls `create_code_channel`, which sets
    `code_channel_id` so the listener knows the work moved there.
    """

    client: WebClient
    user_id: str
    channel_id: str
    message_ts: str
    thread_ts: str
    code_channel_id: str | None = None
