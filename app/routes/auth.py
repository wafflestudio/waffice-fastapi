import logging
from datetime import timedelta

# Google OAuth configuration
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import jwt
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.secrets import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    JWT_EXPIRE_HOURS,
    JWT_SECRET_KEY,
)
from app.deps.auth import JWT_ALGORITHM, get_current_user
from app.models import Qualification, User
from app.schemas import AuthStatus, Response, SignupRequest, Token
from app.services import UserService

logger = logging.getLogger(__name__)

JWT_EXPIRE_MINUTES = JWT_EXPIRE_HOURS * 60

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


@router.get(
    "/google",
    summary="Initiate Google OAuth login",
    description="Redirects the user to Google's OAuth consent page. After authentication, Google redirects back to `/auth/google/callback`.",
    responses={
        302: {"description": "Redirect to Google OAuth consent page"},
    },
)
async def google_login(request: Request):
    """
    Start the Google OAuth login flow.

    This endpoint redirects users to Google's OAuth consent page where they
    can authorize the application to access their profile and email.

    After successful authorization, Google redirects to `/auth/google/callback`
    with an authorization code.
    """
    redirect_uri = GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get(
    "/google/callback",
    summary="Handle Google OAuth callback",
    description="Processes the OAuth callback from Google and returns authentication status.",
    responses={
        200: {
            "description": "Authentication successful",
            "content": {
                "application/json": {
                    "examples": {
                        "new_user": {
                            "summary": "New user (needs signup)",
                            "value": {
                                "ok": True,
                                "data": {"status": "new", "user": None},
                            },
                        },
                        "pending_user": {
                            "summary": "Pending user (awaiting approval)",
                            "value": {
                                "ok": True,
                                "data": {
                                    "status": "pending",
                                    "token": {
                                        "access_token": "eyJ...",
                                        "token_type": "bearer",
                                    },
                                    "user": {"id": 1, "name": "John", "...": "..."},
                                },
                            },
                        },
                        "active_user": {
                            "summary": "Active user (approved)",
                            "value": {
                                "ok": True,
                                "data": {
                                    "status": "active",
                                    "token": {
                                        "access_token": "eyJ...",
                                        "token_type": "bearer",
                                    },
                                    "user": {"id": 1, "name": "John", "...": "..."},
                                },
                            },
                        },
                    }
                }
            },
        },
        400: {"description": "OAuth authorization failed or missing user info"},
    },
)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """
    Handle the OAuth callback from Google.

    This endpoint is called by Google after user authorization. It processes
    the authorization code and determines the user's authentication status:

    - **new**: User not found in database. Frontend should redirect to signup.
    - **pending**: User exists but awaiting admin approval. Limited API access.
    - **active**: User approved. Full API access based on qualification level.

    For existing users, a JWT token is returned for subsequent API calls.
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


@router.post(
    "/signup",
    response_model=Response[Token],
    summary="Complete user signup",
    description="Complete registration after OAuth authentication.",
    responses={
        200: {"description": "Signup successful, returns access token"},
        501: {"description": "Not implemented - requires OAuth session"},
    },
)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """
    Complete user signup after OAuth authentication.

    This endpoint should be called after receiving a 'new' status from
    the OAuth callback. It creates the user record and returns an access token.

    **Note**: This endpoint requires an active OAuth session to associate
    the Google account with the new user.
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


@router.get(
    "/me",
    response_model=Response[AuthStatus],
    summary="Get current auth status",
    description="Returns the current user's authentication status and profile.",
    responses={
        200: {"description": "Current authentication status"},
        401: {"description": "Not authenticated - invalid or missing token"},
    },
)
async def get_auth_status(
    current_user: User = Depends(get_current_user),
):
    """
    Get the current user's authentication status.

    Returns the user's status ('pending' or 'active') along with their
    full profile information. Useful for checking session validity and
    determining available features based on approval status.
    """
    if current_user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(ok=True, data=AuthStatus(status=auth_status, user=current_user))
