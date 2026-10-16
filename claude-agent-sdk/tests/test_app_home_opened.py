from listeners.events.app_home_opened import handle_app_home_opened


class TestAppHomeOpened:
    async def test_publishes_home_view_when_tab_is_home(self, client, context):
        await handle_app_home_opened(
            client=client, context=context, event={"tab": "home"}
        )

        publish = client.views_publish.call_args.kwargs
        assert publish["user_id"] == "U123"
        assert publish["view"].to_dict()["type"] == "home"

    async def test_does_nothing_when_tab_is_messages(self, client, context):
        await handle_app_home_opened(
            client=client, context=context, event={"tab": "messages"}
        )

        client.views_publish.assert_not_called()
