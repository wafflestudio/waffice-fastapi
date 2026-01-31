import logging
from datetime import datetime, timedelta, timezone

# Google OAuth configuration
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from jose import JWTError, jwt
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
from app.exceptions import InvalidAuthTokenError, UserNotRegisteredError
from app.models import Qualification, User
from app.schemas import (
    AuthResult,
    AuthStatus,
    Response,
    SigninRequest,
    SignupRequest,
    Token,
)
from app.services import UserService

logger = logging.getLogger(__name__)

JWT_EXPIRE_MINUTES = JWT_EXPIRE_HOURS * 60
AUTH_TOKEN_EXPIRE_MINUTES = 10

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


def create_auth_token(google_id: str, email: str, is_new: bool) -> str:
    """Create temporary auth token for signin/signup flow"""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=AUTH_TOKEN_EXPIRE_MINUTES)

    payload = {
        "type": "auth",
        "google_id": google_id,
        "email": email,
        "is_new": is_new,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_auth_token(auth_token: str) -> dict:
    """Decode and validate auth token. Raises InvalidAuthTokenError if invalid."""
    try:
        payload = jwt.decode(auth_token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "auth":
            raise InvalidAuthTokenError("Invalid token type")
        return payload
    except JWTError as e:
        logger.warning(f"Auth token decode failed: {e}")
        raise InvalidAuthTokenError()


@router.get(
    "/google",
    summary="Initiate Google OAuth login",
    description="Redirects the user to Google's OAuth consent page. After authentication, Google redirects back to `/auth/redirect`.",
    responses={
        302: {"description": "Redirect to Google OAuth consent page"},
    },
)
async def google_login(request: Request):
    """
    Start the Google OAuth login flow.

    This endpoint redirects users to Google's OAuth consent page where they
    can authorize the application to access their profile and email.

    After successful authorization, Google redirects to `/auth/redirect`
    with an authorization code.
    """
    redirect_uri = GOOGLE_REDIRECT_URI
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get(
    "/redirect",
    response_model=Response[AuthStatus],
    summary="Handle Google OAuth callback",
    description="Processes the OAuth callback from Google and returns an auth token.",
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
                                "data": {
                                    "status": "new",
                                    "auth_token": "eyJ...",
                                },
                            },
                        },
                        "pending_user": {
                            "summary": "Pending user (use signin endpoint)",
                            "value": {
                                "ok": True,
                                "data": {
                                    "status": "pending",
                                    "auth_token": "eyJ...",
                                },
                            },
                        },
                        "active_user": {
                            "summary": "Active user (use signin endpoint)",
                            "value": {
                                "ok": True,
                                "data": {
                                    "status": "active",
                                    "auth_token": "eyJ...",
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
    the authorization code and returns an auth_token for subsequent signin/signup:

    - **new**: User not found in database. Use `/auth/signup` with auth_token.
    - **pending**: User exists but awaiting approval. Use `/auth/signin` with auth_token.
    - **active**: User approved. Use `/auth/signin` with auth_token.

    The auth_token is valid for 10 minutes.
    """
    from fastapi import HTTPException, status

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
        # New user
        auth_token = create_auth_token(google_id, email, is_new=True)
        return Response(ok=True, data=AuthStatus(status="new", auth_token=auth_token))

    # Existing user
    auth_token = create_auth_token(google_id, email, is_new=False)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(ok=True, data=AuthStatus(status=auth_status, auth_token=auth_token))


@router.post(
    "/signin",
    response_model=Response[AuthResult],
    summary="Sign in existing user",
    description="Exchange auth token for JWT access token (existing users only).",
    responses={
        200: {"description": "Signin successful, returns access token and user"},
        400: {"description": "Invalid auth token or user not registered"},
    },
)
async def signin(request: SigninRequest, db: Session = Depends(get_db)):
    """
    Sign in an existing user with an auth token.

    This endpoint exchanges the temporary auth_token (from OAuth callback)
    for a JWT access token. Only works for registered users.

    If the auth_token indicates a new user, this endpoint will return an error
    directing them to use `/auth/signup` instead.
    """
    payload = decode_auth_token(request.auth_token)

    if payload.get("is_new"):
        raise UserNotRegisteredError()

    google_id = payload["google_id"]
    email = payload["email"]

    # Find user
    user = UserService.get_by_google_id(db, google_id)
    if not user:
        user = UserService.get_by_email(db, email)

    if not user:
        raise UserNotRegisteredError()

    # Update google_id if user was found by email
    if not user.google_id:
        UserService.update(db, user, google_id=google_id)

    # Generate JWT
    access_token = create_access_token(user.id, user.email, user.google_id)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            token=Token(access_token=access_token),
            user=user,
        ),
    )


@router.post(
    "/signup",
    response_model=Response[AuthResult],
    summary="Complete user signup",
    description="Complete registration with auth token and user details.",
    responses={
        200: {"description": "Signup successful, returns access token and user"},
        400: {"description": "Invalid auth token"},
    },
)
async def signup(request: SignupRequest, db: Session = Depends(get_db)):
    """
    Complete user signup after OAuth authentication.

    This endpoint should be called after receiving a 'new' status from
    the OAuth callback. It creates the user record and returns an access token.

    For idempotency, if the user already exists (same google_id or email),
    this endpoint will return the existing user instead of creating a duplicate.
    """
    payload = decode_auth_token(request.auth_token)

    google_id = payload["google_id"]
    email = payload["email"]

    # Check for existing user (idempotency)
    user = UserService.get_by_google_id(db, google_id)
    if not user:
        user = UserService.get_by_email(db, email)

    if user:
        # User already exists - return existing user (idempotency)
        if not user.google_id:
            UserService.update(db, user, google_id=google_id)
    else:
        # Create new user
        user = UserService.create(
            db,
            google_id=google_id,
            email=email,
            name=request.name,
            phone=request.phone,
            affiliation=request.affiliation,
            bio=request.bio,
            github_username=request.github_username,
        )

    # Generate JWT
    access_token = create_access_token(user.id, user.email, user.google_id)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            token=Token(access_token=access_token),
            user=user,
        ),
    )


@router.get(
    "/me",
    response_model=Response[AuthResult],
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

    # Generate a fresh token
    access_token = create_access_token(
        current_user.id, current_user.email, current_user.google_id
    )

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            token=Token(access_token=access_token),
            user=current_user,
        ),
    )
