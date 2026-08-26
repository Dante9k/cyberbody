import io

from PIL import Image

from cyberbody.capture import fit_for_model, load_frame_image, perceptual_hash
from cyberbody.models import CaptureFrame, Rect


def test_fit_for_model_preserves_aspect_ratio():
    image = Image.new("RGB", (2400, 1200), "white")

    resized = fit_for_model(image, 1600, 900)

    assert resized.size == (1600, 800)
    assert fit_for_model(Image.new("RGB", (800, 600)), 1600, 900).size == (800, 600)


def test_perceptual_hash_changes_with_visible_content():
    dark = Image.new("RGB", (32, 32), "black")
    split = Image.new("RGB", (32, 32), "black")
    for x in range(16):
        for y in range(32):
            split.putpixel((x, y), (255, 255, 255))

    assert perceptual_hash(dark) != perceptual_hash(split)


def test_load_frame_image_can_use_in_memory_png():
    image = Image.new("RGB", (20, 10), "navy")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    frame = CaptureFrame(
        round_index=1,
        source_rect=Rect(0, 0, 20, 10),
        source_width=20,
        source_height=10,
        model_width=20,
        model_height=10,
        model_png=buffer.getvalue(),
    )

    assert load_frame_image(frame).size == (20, 10)
