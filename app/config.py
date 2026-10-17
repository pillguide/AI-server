"""Package-relative paths; never depend on the research server filesystem."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    root: Path = PACKAGE_ROOT
    api_key: str = field(default_factory=lambda: os.getenv("PILLGUIDE_API_KEY", ""))
    device: str = field(default_factory=lambda: os.getenv("PILLGUIDE_DEVICE", "cuda:0"))

    def __post_init__(self):
        if self.device not in ("cuda:0", "cpu"):
            raise ValueError("PILLGUIDE_DEVICE must be cuda:0 or explicit cpu smoke mode")

    @property
    def inference(self):
        return json.loads((self.root / "config/inference.json").read_text(encoding="utf-8"))

    def validate_key(self):
        if len(self.api_key) < 32:
            raise ValueError("Set PILLGUIDE_API_KEY to a locally generated secret of at least 32 characters")
