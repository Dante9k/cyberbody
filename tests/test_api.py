import threading
from types import SimpleNamespace

import pytest

from cyberbody.api import OpenAIComputerClient, _retryable, parse_turn


def test_parse_computer_turn_and_final_message():
    response = SimpleNamespace(
        id="resp_1",
        output=[
            SimpleNamespace(
                type="computer_call",
                call_id="call_1",
                actions=[
                    SimpleNamespace(type="click", x=10, y=20, button="left", keys=[]),
                    SimpleNamespace(type="type", text="hello", keys=[]),
                ],
            )
        ],
        output_text="",
    )
    turn = parse_turn(response)
    assert turn.response_id == "resp_1"
    assert turn.call_id == "call_1"
    assert [action.type for action in turn.actions] == ["click", "type"]

    final = parse_turn(SimpleNamespace(id="resp_2", output=[], output_text="完成"))
    assert not final.has_computer_call
    assert final.final_text == "完成"


def test_only_transient_api_failures_are_retried():
    assert _retryable(RuntimeError("network"))
    assert _retryable(SimpleNamespace(status_code=429))
    assert _retryable(SimpleNamespace(status_code=503))
    assert not _retryable(SimpleNamespace(status_code=401))


class FakeResponses:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            id=f"resp_{len(self.requests)}",
            output=[
                SimpleNamespace(
                    type="computer_call",
                    call_id=f"call_{len(self.requests)}",
                    actions=[SimpleNamespace(type="screenshot")],
                )
            ],
            output_text="",
        )


def test_client_uses_ga_computer_tool_and_screenshot_output_schema():
    responses = FakeResponses()
    client = OpenAIComputerClient(
        "",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )
    stop = threading.Event()

    first = client.start("打开项目", stop)
    client.continue_with_screenshot(first.response_id, "call_1", b"png", stop)

    assert responses.requests[0]["tools"] == [{"type": "computer"}]
    screenshot_output = responses.requests[1]["input"][0]
    assert screenshot_output["type"] == "computer_call_output"
    assert screenshot_output["output"]["type"] == "computer_screenshot"
    assert screenshot_output["output"]["detail"] == "original"
    assert screenshot_output["output"]["image_url"].startswith("data:image/png;base64,")


def test_retry_loop_never_retries_authentication_failure():
    class AuthenticationFailure(RuntimeError):
        status_code = 401

    attempts = 0

    def fail():
        nonlocal attempts
        attempts += 1
        raise AuthenticationFailure("unauthorized")

    client = OpenAIComputerClient(
        "",
        client=SimpleNamespace(responses=SimpleNamespace()),
        retries=3,
    )

    with pytest.raises(AuthenticationFailure):
        client._call_with_retry(fail, threading.Event())
    assert attempts == 1


def test_parse_turn_requires_response_id():
    with pytest.raises(ValueError, match="missing its id"):
        parse_turn(SimpleNamespace(output=[], output_text=""))
