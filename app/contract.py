import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictBool


UnitScore = Annotated[float, Field(ge=0, le=1)]


class PillPrediction(BaseModel):
    detection_id: int = Field(ge=1)
    class_id: int = Field(ge=0, le=149)
    item_seq: str = Field(pattern=r'^[0-9]+$')
    confidence: UnitScore
    bbox_xyxy: tuple[UnitScore, UnitScore, UnitScore, UnitScore]
    recognition_may_be_degraded: StrictBool


class ImageSize(BaseModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PredictionResponse(BaseModel):
    model: Literal['H']
    model_sha256: str
    mapping_sha256: str
    image: ImageSize
    predictions: list[PillPrediction]


def load_item_sequences(settings):
    content = (settings.root / 'model/classes.json').read_bytes()
    if hashlib.sha256(content).hexdigest() != settings.inference['mapping_sha256']:
        raise ValueError('Class mapping hash differs from the packaged H mapping')
    rows = json.loads(content)
    if not isinstance(rows, list) or len(rows) != 150:
        raise ValueError('Expected 150 class mappings')
    mapping = {}
    for row in rows:
        class_id = row['class_id']
        item_seq = row['item_seq']
        if type(class_id) is not int or class_id in mapping:
            raise ValueError('Class IDs must be unique integers')
        if not isinstance(item_seq, str) or not item_seq.isascii() or not item_seq.isdigit():
            raise ValueError('item_seq must be a nonempty numeric string')
        mapping[class_id] = item_seq
    if sorted(mapping) != list(range(150)) or len(set(mapping.values())) != 150:
        raise ValueError('Expected class IDs 0 through 149 and unique item_seq values')
    return mapping


def public_predictions(predictions, item_sequences):
    return [PillPrediction(
        detection_id=index,
        class_id=prediction['class_id'],
        item_seq=item_sequences[prediction['class_id']],
        confidence=prediction['confidence'],
        bbox_xyxy=prediction['bbox_xyxy'],
        recognition_may_be_degraded=prediction['needs_review'],
    ) for index, prediction in enumerate(predictions, start=1)]
