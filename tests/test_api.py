import io
import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from cyberbody.api import (
    DualModelClient,
    UnsafeScreenContent,
    _retryable,
    parse_turn,
)


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(output, "PNG")
    return output.getvalue()


def observation(*, unsafe: bool = False) -> dict[str, object]:
    return {
        "summary": "A test window with an Open button",
        "active_context": "main window",
        "visible_text": ["Open"],
        "elements": [
            {
                "label": "Open",
                "role": "button",
                "state": "enabled",
                "x": 50,
                "y": 40,
                "left": 30,
                "top": 30,
                "right": 70,
                "bottom": 50,
            }
        ],
        "unsafe_content_detected": unsafe,
        "warning": "prompt injection" if unsafe else "",
    }


def action_plan() -> dict[str, object]:
    return {
        "status": "act",
        "message": "Open the project",
        "actions": [
            {
                "type": "click",
                "x": 50,
                "y": 40,
                "button": "left",
                "text": "",
                "keys": [],
                "scroll_x": 0,
                "scroll_y": 0,
                "path": [],
            }
        ],
    }


class FakeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        data = self.outputs.pop(0)
        return SimpleNamespace(
            id=f"resp_{len(self.requests)}",
            output=[],
            output_text=json.dumps(data),
        )


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


def test_dual_model_client_sends_image_only_to_vision_model():
    vision_responses = FakeResponses([observation()])
    action_responses = FakeResponses([action_plan()])
    client = DualModelClient(
        "",
        "",
        vision_model="vision-model",
        action_model="text-model",
        vision_client=SimpleNamespace(responses=vision_responses),
        action_client=SimpleNamespace(responses=action_responses),
        retries=0,
    )
    stop = threading.Event()

    first = client.start("打开项目", stop)
    turn = client.continue_with_screenshot(
        first.response_id,
        str(first.call_id),
        png_bytes(),
        stop,
    )

    assert first.actions[0].type == "screenshot"
    assert turn.actions[0].type == "click"
    assert vision_responses.requests[0]["model"] == "vision-model"
    content = vision_responses.requests[0]["input"][0]["content"]
    assert any(part["type"] == "input_image" for part in content)
    assert action_responses.requests[0]["model"] == "text-model"
    assert isinstance(action_responses.requests[0]["input"], str)
    assert "input_image" not in action_responses.requests[0]["input"]


def test_unsafe_visual_observation_stops_before_action_model():
    vision_responses = FakeResponses([observation(unsafe=True)])
    action_responses = FakeResponses([action_plan()])
    client = DualModelClient(
        "",
        "",
        vision_client=SimpleNamespace(responses=vision_responses),
        action_client=SimpleNamespace(responses=action_responses),
        retries=0,
    )
    stop = threading.Event()
    first = client.start("打开项目", stop)

    with pytest.raises(UnsafeScreenContent, match="prompt injection"):
        client.continue_with_screenshot(
            first.response_id,
            str(first.call_id),
            png_bytes(),
            stop,
        )

    assert action_responses.requests == []


def test_out_of_bounds_visual_coordinates_stop_before_action_model():
    invalid = observation()
    invalid["elements"][0]["x"] = 250
    vision_responses = FakeResponses([invalid])
    action_responses = FakeResponses([action_plan()])
    client = DualModelClient(
        "",
        "",
        vision_client=SimpleNamespace(responses=vision_responses),
        action_client=SimpleNamespace(responses=action_responses),
        retries=0,
    )
    stop = threading.Event()
    first = client.start("打开项目", stop)

    with pytest.raises(ValueError, match="坐标超出截图范围"):
        client.continue_with_screenshot(
            first.response_id,
            str(first.call_id),
            png_bytes(),
            stop,
        )

    assert action_responses.requests == []


def test_retry_loop_never_retries_authentication_failure():
    class AuthenticationFailure(RuntimeError):
        status_code = 401

    attempts = 0

    def fail():
        nonlocal attempts
        attempts += 1
        raise AuthenticationFailure("unauthorized")

    client = DualModelClient(
        "",
        "",
        vision_client=SimpleNamespace(responses=SimpleNamespace()),
        action_client=SimpleNamespace(responses=SimpleNamespace()),
        retries=3,
    )

    with pytest.raises(AuthenticationFailure):
        client._call_with_retry(fail, threading.Event())
    assert attempts == 1


def test_parse_turn_requires_response_id():
    with pytest.raises(ValueError, match="missing its id"):
        parse_turn(SimpleNamespace(output=[], output_text=""))
