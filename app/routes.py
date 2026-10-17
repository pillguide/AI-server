import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from .config import UploadLimits
from .contract import HealthResponse, PredictionResponse
from .imaging import ImageTooLargeError, InvalidImageError
from .service import InferenceBusyError, InferenceNotReadyError, PredictionService

LOG = logging.getLogger('pillguide')
router = APIRouter()


async def get_service(request: Request) -> PredictionService:
    service = getattr(request.app.state, 'inference', None)
    if service is None:
        raise HTTPException(503, 'Model is not ready')
    return service


async def get_limits(request: Request) -> UploadLimits:
    return request.app.state.settings.limits


@router.get('/health', response_model=HealthResponse)
async def health(service: Annotated[PredictionService, Depends(get_service)]) -> HealthResponse:
    return service.health


@router.post('/predict', response_model=PredictionResponse)
async def predict(
    service: Annotated[PredictionService, Depends(get_service)],
    limits: Annotated[UploadLimits, Depends(get_limits)],
    file: Annotated[UploadFile, File()],
) -> PredictionResponse:
    try:
        if file.content_type not in ('image/jpeg', 'image/png', 'application/octet-stream'):
            raise HTTPException(415, 'Upload a JPEG or PNG image')
        data = await file.read(limits.max_upload_bytes + 1)
    finally:
        await file.close()
    if not data:
        raise HTTPException(400, 'Empty image upload')
    if len(data) > limits.max_upload_bytes:
        raise HTTPException(413, 'Image file exceeds 10 MiB')
    try:
        return await run_in_threadpool(service.predict, data)
    except InferenceBusyError as error:
        raise HTTPException(503, str(error), headers={'Retry-After': '1'}) from None
    except InferenceNotReadyError as error:
        raise HTTPException(503, str(error)) from None
    except ImageTooLargeError as error:
        raise HTTPException(413, str(error)) from None
    except InvalidImageError as error:
        raise HTTPException(415, str(error)) from None
    except Exception:
        LOG.exception('Model H inference failed')
        raise HTTPException(500, 'Inference failed; check server logs') from None
