from __future__ import annotations

import io
from pathlib import Path
from typing import cast

from PIL import Image, ImageGrab

from .models import CaptureFrame, Rect, TargetWindow
from .storage import SessionStore
from .windows import WindowManager


def perceptual_hash(image: Image.Image) -> int:
    sample = image.convert("L").resize((16, 16), Image.Resampling.LANCZOS)
    pixels = cast(list[int], sample.get_flattened_data())
    average = sum(pixels) / len(pixels)
    result = 0
    for index, pixel in enumerate(pixels):
        if pixel >= average:
            result |= 1 << index
    return result


def fit_for_model(image: Image.Image, max_width: int, max_height: int) -> Image.Image:
    if image.width <= max_width and image.height <= max_height:
        return image.copy()
    scale = min(max_width / image.width, max_height / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


class CaptureService:
    def __init__(
        self,
        windows: WindowManager,
        store: SessionStore,
        max_width: int = 1600,
        max_height: int = 900,
    ) -> None:
        self.windows = windows
        self.store = store
        self.max_width = max_width
        self.max_height = max_height

    def capture(self, target: TargetWindow, round_index: int) -> tuple[CaptureFrame, Image.Image]:
        self.windows.refresh(target)
        capture_hwnd, bounds = self.windows.capture_target(target)
        if bounds.width <= 0 or bounds.height <= 0:
            raise RuntimeError("目标窗口没有可捕获区域")
        source = ImageGrab.grab(bbox=bounds.as_bbox(), all_screens=True)
        if source.width != bounds.width or source.height != bounds.height:
            raise RuntimeError("截图尺寸与目标窗口不一致")
        model_image = fit_for_model(source, self.max_width, self.max_height)
        buffer = io.BytesIO()
        model_image.save(buffer, format="PNG", optimize=True)
        source_path, model_path = self.store.save_capture(round_index, source, model_image)
        frame = CaptureFrame(
            round_index=round_index,
            source_rect=Rect(bounds.left, bounds.top, bounds.right, bounds.bottom),
            source_width=source.width,
            source_height=source.height,
            model_width=model_image.width,
            model_height=model_image.height,
            capture_hwnd=capture_hwnd,
            source_path=source_path,
            model_path=model_path,
            perceptual_hash=perceptual_hash(model_image),
            model_png=buffer.getvalue(),
        )
        return frame, model_image


def load_frame_image(frame: CaptureFrame) -> Image.Image:
    if frame.model_path is None:
        return Image.open(io.BytesIO(frame.model_png)).copy()
    with Image.open(Path(frame.model_path)) as image:
        return image.copy()
