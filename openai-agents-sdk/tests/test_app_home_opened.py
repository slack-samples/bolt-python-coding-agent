from unittest.mock import Mock

from slack_bolt import BoltContext
from slack_sdk import WebClient

from listeners.events.app_home_opened import handle_app_home_opened


class TestAppHomeOpened:
    def setup_method(self):
        self.client = Mock(WebClient)
        self.context = Mock(BoltContext)
        self.context.user_id = "U123"

    def test_publishes_home_view_when_tab_is_home(self):
        handle_app_home_opened(
            client=self.client, context=self.context, event={"tab": "home"}
        )

        publish = self.client.views_publish.call_args.kwargs
        assert publish["user_id"] == "U123"
        assert publish["view"].to_dict()["type"] == "home"

    def test_does_nothing_when_tab_is_messages(self):
        handle_app_home_opened(
            client=self.client, context=self.context, event={"tab": "messages"}
        )

        self.client.views_publish.assert_not_called()
