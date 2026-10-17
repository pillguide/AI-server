from collections.abc import Mapping, Sequence
from contextlib import closing
from threading import Lock
from typing import Any, Protocol

from PIL import Image

from .config import Settings
from .contract import HealthResponse, ImageSize, PredictionResponse, public_predictions
from .imaging import ImageDecoder


class PredictionEngine(Protocol):
    model_sha256: str
    mapping_sha256: str

    def predict(self, image: Image.Image) -> Sequence[Mapping[str, Any]]: ...


class InferenceBusyError(RuntimeError):
    pass


class InferenceNotReadyError(RuntimeError):
    pass


class PredictionService:
    def __init__(
        self, engine: PredictionEngine, item_sequences: Mapping[int, str], settings: Settings,
    ) -> None:
        self._engine: PredictionEngine | None = engine
        self._item_sequences = dict(item_sequences)
        self._decoder = ImageDecoder(settings.limits.max_image_pixels)
        self._gate = Lock()
        self._health = HealthResponse(
            device=settings.device,
            model_sha256=engine.model_sha256,
            mapping_sha256=engine.mapping_sha256,
        )

    @property
    def health(self) -> HealthResponse:
        return self._health

    def predict(self, data: bytes) -> PredictionResponse:
        if not self._gate.acquire(blocking=False):
            raise InferenceBusyError('Inference is busy; retry shortly')
        try:
            if self._engine is None:
                raise InferenceNotReadyError('Model is not ready')
            with closing(self._decoder.decode(data)) as image:
                predictions = self._engine.predict(image)
                return PredictionResponse(
                    model='H',
                    model_sha256=self._health.model_sha256,
                    mapping_sha256=self._health.mapping_sha256,
                    image=ImageSize(width=image.width, height=image.height),
                    predictions=public_predictions(predictions, self._item_sequences),
                )
        finally:
            self._gate.release()

    def close(self) -> None:
        with self._gate:
            self._engine = None
