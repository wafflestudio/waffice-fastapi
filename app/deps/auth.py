from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.secrets import JWT_SECRET_KEY
from app.models import Qualification, User
from app.services import UserService

JWT_ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/google")


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """
    Decode JWT token and get current user.
    Raises 401 if token is invalid or user not found.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = UserService.get(db, int(user_id))
    if user is None:
        raise credentials_exception

    return user


async def require_associate(user: User = Depends(get_current_user)) -> User:
    """
    Require user to be at least associate level (not pending).
    Raises 403 if user is pending.
    """
    if user.qualification == Qualification.PENDING:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Associate membership or higher required",
        )
    return user


async def require_regular(user: User = Depends(get_current_user)) -> User:
    """
    Require user to be regular or active member.
    Raises 403 if user is pending or associate.
    """
    if user.qualification not in (Qualification.REGULAR, Qualification.ACTIVE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Regular membership or higher required",
        )
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Require user to be admin.
    Raises 403 if user is not admin.
    """
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin permission required"
        )
    return user
