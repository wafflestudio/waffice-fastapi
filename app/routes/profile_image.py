from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import require_associate
from app.exceptions import InvalidProfileImageError, ProfileImageTooLargeError
from app.models import User
from app.schemas import Response, UserDetail
from app.services import OCIObjectStorageService, UserService

router = APIRouter()

MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024
PROFILE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


@router.post("/upload", response_model=Response[UserDetail])
async def upload_profile_image(
    file: UploadFile = File(...),
    current_user: User = Depends(require_associate),
    db: Session = Depends(get_db),
):
    if file.content_type not in PROFILE_IMAGE_TYPES:
        raise InvalidProfileImageError()

    body = await file.read()
    if len(body) > MAX_PROFILE_IMAGE_SIZE:
        raise ProfileImageTooLargeError()

    storage = OCIObjectStorageService()
    old_url = current_user.avatar_url
    avatar_url = storage.upload_profile_image(current_user.id, file, body)
    updated_user = UserService.update(db, current_user, avatar_url=avatar_url)
    storage.delete_profile_image(current_user.id, old_url)

    return Response(ok=True, data=updated_user)
