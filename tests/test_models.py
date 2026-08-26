from cyberbody.models import CaptureFrame, ComputerAction, Rect, hamming_distance


def test_rect_and_coordinate_mapping_support_negative_screen_coordinates():
    frame = CaptureFrame(
        round_index=1,
        source_rect=Rect(-1920, 100, 0, 1180),
        source_width=1920,
        source_height=1080,
        model_width=1600,
        model_height=900,
    )
    assert frame.to_screen(800, 450) == (-960, 640)
    assert frame.model_point_in_bounds(1599, 899)
    assert not frame.model_point_in_bounds(1600, 900)


def test_computer_action_parses_object_and_dict_drag_points():
    action = ComputerAction.from_api(
        {
            "type": "drag",
            "button": "left",
            "keys": ["CTRL"],
            "path": [[10, 20], {"x": 30, "y": 40}],
        }
    )
    assert action.path == ((10.0, 20.0), (30.0, 40.0))
    assert action.keys == ("CTRL",)
    assert action.is_pointer_action


def test_computer_action_normalizes_api_values():
    action = ComputerAction.from_api({"type": " CLICK ", "x": "12.5", "y": 8, "button": "LEFT"})

    assert action.type == "click"
    assert action.x == 12.5
    assert action.y == 8.0
    assert action.button == "left"


def test_coordinate_mapping_is_exact_at_common_dpi_scaled_sizes():
    for physical_width, physical_height in ((1250, 750), (1500, 900), (2000, 1200)):
        frame = CaptureFrame(
            round_index=1,
            source_rect=Rect(100, -200, 100 + physical_width, -200 + physical_height),
            source_width=physical_width,
            source_height=physical_height,
            model_width=1000,
            model_height=600,
        )

        assert frame.to_screen(500, 300) == (
            100 + physical_width // 2,
            -200 + physical_height // 2,
        )


def test_hamming_distance_counts_changed_bits():
    assert hamming_distance(0b1010, 0b1111) == 2
