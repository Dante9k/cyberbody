import importlib

import pytest

from cyberbody.models import CaptureFrame, ComputerAction, Rect

input_module = importlib.import_module("cyberbody.input")
ActionExecutionError = input_module.ActionExecutionError
InputExecutor = input_module.InputExecutor


def frame() -> CaptureFrame:
    return CaptureFrame(
        round_index=1,
        source_rect=Rect(-1920, 100, 0, 1180),
        source_width=1920,
        source_height=1080,
        model_width=1600,
        model_height=900,
    )


def test_pointer_validation_rejects_points_outside_model_frame():
    with pytest.raises(ActionExecutionError, match="超出截图范围"):
        InputExecutor._validate_points(
            ComputerAction(type="click", x=1600, y=10),
            frame(),
        )


def test_pointer_action_requires_both_coordinates():
    with pytest.raises(ActionExecutionError, match="缺少坐标"):
        InputExecutor._screen_point(ComputerAction(type="click"), frame())


def test_absolute_mapping_supports_negative_virtual_desktop(monkeypatch):
    monkeypatch.setattr(
        input_module,
        "virtual_screen_rect",
        lambda: Rect(-1920, 0, 1920, 1080),
    )

    assert InputExecutor._absolute(-1920, 0) == (0, 0)
    assert InputExecutor._absolute(1919, 1079) == (65535, 65535)
