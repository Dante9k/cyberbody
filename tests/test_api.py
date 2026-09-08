import io
import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from cyberbody.api import (
    DualModelClient,
    NativeComputerClient,
    OpenAIComputerClient,
    PlanningBlocked,
    UnsafeScreenContent,
    _retryable,
    parse_turn,
)
from cyberbody.models import ComputerAction


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


class FakeNativeResponses:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.outputs.pop(0)


def computer_response(response_id, actions, *, checks=(), output_text=""):
    return SimpleNamespace(
        id=response_id,
        output=[
            SimpleNamespace(
                type="computer_call",
                call_id=f"call_{response_id}",
                actions=[SimpleNamespace(**action) for action in actions],
                pending_safety_checks=list(checks),
            )
        ]
        if actions
        else [],
        output_text=output_text,
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


def test_native_computer_client_preserves_responses_conversation():
    responses = FakeNativeResponses(
        [
            computer_response("resp_1", [{"type": "screenshot"}]),
            computer_response(
                "resp_2",
                [{"type": "click", "x": 50, "y": 40, "button": "left", "keys": []}],
            ),
        ]
    )
    client = NativeComputerClient(
        "",
        model="computer-model",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )

    first = client.start("打开项目", threading.Event())
    turn = client.continue_with_screenshot(
        first.response_id,
        str(first.call_id),
        png_bytes(),
        threading.Event(),
    )

    assert first.actions[0].type == "screenshot"
    assert turn.actions[0].type == "click"
    assert responses.requests[0]["tools"] == [{"type": "computer"}]
    assert responses.requests[1]["previous_response_id"] == "resp_1"
    output = responses.requests[1]["input"][0]
    assert output["call_id"] == "call_resp_1"
    assert output["output"]["type"] == "computer_screenshot"
    assert output["output"]["detail"] == "original"


def test_native_computer_client_rejects_action_before_first_screenshot():
    responses = FakeNativeResponses(
        [
            computer_response(
                "resp_1",
                [{"type": "click", "x": 10, "y": 10, "button": "left", "keys": []}],
            )
        ]
    )
    client = NativeComputerClient(
        "",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )

    with pytest.raises(PlanningBlocked, match="观察目标窗口前"):
        client.start("打开项目", threading.Event())


def test_native_computer_client_requires_initial_screenshot_call():
    responses = FakeNativeResponses([computer_response("resp_1", [], output_text="完成")])
    client = NativeComputerClient(
        "",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )

    with pytest.raises(PlanningBlocked, match="没有请求首张"):
        client.start("打开项目", threading.Event())


def test_legacy_openai_client_constructor_maps_to_native_mode():
    responses = FakeNativeResponses([computer_response("resp_1", [{"type": "screenshot"}])])
    client = OpenAIComputerClient(
        "",
        "legacy-model",
        30,
        0,
        SimpleNamespace(responses=responses),
    )

    client.start("打开项目", threading.Event())

    assert responses.requests[0]["model"] == "legacy-model"


def test_native_safety_checks_require_confirmation_and_are_acknowledged():
    check = {"id": "safe_1", "code": "computer_initialize_state", "message": "Confirm"}
    responses = FakeNativeResponses(
        [
            computer_response("resp_1", [{"type": "screenshot"}]),
            computer_response(
                "resp_2",
                [{"type": "click", "x": 50, "y": 40, "button": "left", "keys": []}],
                checks=[check],
            ),
            computer_response("resp_3", [], output_text="完成"),
        ]
    )
    client = NativeComputerClient(
        "",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )
    stop = threading.Event()

    first = client.start("打开项目", stop)
    second = client.continue_with_screenshot(
        first.response_id, str(first.call_id), png_bytes(), stop
    )
    inspection = client.inspect_action("打开项目", second.actions[0], png_bytes(), stop)
    assert inspection.decision.value == "confirm"
    assert "Confirm" in inspection.reason

    client.acknowledge_safety_checks()
    client.continue_with_screenshot(second.response_id, str(second.call_id), png_bytes(), stop)
    assert responses.requests[2]["input"][0]["acknowledged_safety_checks"] == [check]


def test_native_action_preflight_uses_annotated_image_and_structured_output():
    result = {
        "purpose": "打开项目",
        "target_label": "打开按钮",
        "risk_category": "none",
        "decision": "allow",
        "reason": "普通导航",
    }
    responses = FakeNativeResponses(
        [SimpleNamespace(id="resp_check", output=[], output_text=json.dumps(result))]
    )
    client = NativeComputerClient(
        "",
        model="computer-model",
        client=SimpleNamespace(responses=responses),
        retries=0,
    )

    inspection = client.inspect_action(
        "打开项目",
        ComputerAction(type="click", x=50, y=40),
        png_bytes(),
        threading.Event(),
    )

    assert inspection.purpose == "打开项目"
    assert inspection.decision.value == "allow"
    request = responses.requests[0]
    assert request["model"] == "computer-model"
    assert request["text"]["format"]["type"] == "json_schema"
    assert request["input"][0]["content"][1]["type"] == "input_image"
