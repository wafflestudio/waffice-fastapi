from fastapi import APIRouter, Depends

from app.deps.auth import require_associate
from app.models import User
from app.schemas import PresignedUrlRequest, PresignedUrlResponse, Response
from app.services import S3Service

router = APIRouter()


@router.post("/presigned-url", response_model=Response[PresignedUrlResponse])
async def get_presigned_url(
    request: PresignedUrlRequest,
    _user: User = Depends(require_associate),
):
    """
    Get presigned URL for S3 upload (requires associate or higher).
    Currently returns mock URLs - actual S3 integration pending.
    """
    s3_service = S3Service()
    urls = s3_service.generate_presigned_url(request.filename, request.content_type)

    return Response(
        ok=True,
        data=PresignedUrlResponse(
            upload_url=urls["upload_url"], file_url=urls["file_url"]
        ),
    )
