import logging
import os
from datetime import timedelta

# Google OAuth configuration
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.deps.auth import get_current_user
from app.models import Qualification, User
from app.schemas import AuthStatus, Response, SignupRequest, Token
from app.services import UserService

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback"
)

# JWT Configuration - import from deps to ensure single source of truth
from app.deps.auth import JWT_ALGORITHM, JWT_SECRET_KEY

JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter()


def create_access_token(user_id: int, email: str, google_id: str | None) -> str:
    """Create JWT access token for user"""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=JWT_EXPIRE_MINUTES)

    payload = {
        "user_id": user_id,
        "email": email,
        "google_id": google_id,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "sub": str(user_id),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


@router.get("/google")
async def google_login(request: Request):
    """Initiate Google OAuth login"""
    redirect_uri = GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """
    Handle Google OAuth callback.
    Returns auth status: 'new' (needs signup), 'pending', or 'active'.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        logger.error(f"OAuth authorization failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth authorization failed",
        )

    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get user info"
        )

    google_id = user_info.get("sub")
    email = user_info.get("email")

    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required user information",
        )

    # Check if user exists
    user = UserService.get_by_google_id(db, google_id)
    if not user:
        user = UserService.get_by_email(db, email)

    if not user:
        # New user - return status 'new' without token
        return Response(ok=True, data=AuthStatus(status="new", user=None))

    # Existing user - generate token
    access_token = create_access_token(user.id, user.email, user.google_id)

    # Determine status
    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data={
            "status": auth_status,
            "token": Token(access_token=access_token),
            "user": user,
        },
    )


@router.post("/signup", response_model=Response[Token])
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """
    Complete user signup after OAuth.
    Idempotent: returns existing user if already signed up.
    """
    # This should be called with OAuth context, but for idempotency
    # we'll check by email if provided in request
    # In a real implementation, you'd get google_id from OAuth session

    # For now, we'll create user with email
    # This is a simplified version - in production you'd need OAuth session

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Signup endpoint requires OAuth session implementation",
    )


@router.get("/me", response_model=Response[AuthStatus])
async def get_auth_status(
    current_user: User = Depends(get_current_user),
):
    """Get current authentication status"""
    if current_user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(ok=True, data=AuthStatus(status=auth_status, user=current_user))
