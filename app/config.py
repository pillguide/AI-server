"""Package-relative paths; never depend on the research server filesystem."""
from dataclasses import dataclass, field
from functools import cached_property
import json
import os
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class UploadLimits:
    max_upload_bytes: int
    max_request_bytes: int
    max_image_pixels: int

    def __post_init__(self) -> None:
        for value in (self.max_upload_bytes, self.max_request_bytes, self.max_image_pixels):
            if type(value) is not int or value <= 0:
                raise ValueError('Upload limits must be positive integers')
        if self.max_request_bytes < self.max_upload_bytes:
            raise ValueError('Request limit must include the image file')


@dataclass(frozen=True)
class Settings:
    root: Path = PACKAGE_ROOT
    api_key: str = field(default_factory=lambda: os.getenv("PILLGUIDE_API_KEY", ""), repr=False)
    device: str = field(default_factory=lambda: os.getenv("PILLGUIDE_DEVICE", "cuda:0"))

    def __post_init__(self) -> None:
        if self.device not in ("cuda:0", "cpu"):
            raise ValueError("PILLGUIDE_DEVICE must be cuda:0 or explicit cpu smoke mode")

    @cached_property
    def inference(self) -> dict[str, Any]:
        options = json.loads((self.root / "config/inference.json").read_text(encoding="utf-8"))
        if not isinstance(options, dict):
            raise ValueError('Inference configuration must be a JSON object')
        return options

    @cached_property
    def limits(self) -> UploadLimits:
        return UploadLimits(
            max_upload_bytes=self.inference['max_upload_bytes'],
            max_request_bytes=self.inference['max_request_bytes'],
            max_image_pixels=self.inference['max_image_pixels'],
        )

    def validate_key(self) -> None:
        if len(self.api_key) < 32:
            raise ValueError("Set PILLGUIDE_API_KEY to a locally generated secret of at least 32 characters")
