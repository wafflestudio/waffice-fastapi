import logging
from datetime import datetime, timedelta, timezone

# Google OAuth configuration
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.secrets import (
    FRONTEND_ORIGIN,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    JWT_EXPIRE_HOURS,
    JWT_SECRET_KEY,
)
from app.deps.auth import JWT_ALGORITHM, get_current_user
from app.exceptions import InvalidAuthTokenError, UserNotRegisteredError
from app.models import Qualification, User
from app.schemas import (
    AuthResult,
    AuthStatus,
    GoogleTokenRequest,
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


def get_allowed_origins() -> set[str]:
    """Returns the set of allowed frontend origins for OAuth redirect."""
    origins = {"http://localhost:3000"}
    if FRONTEND_ORIGIN:
        origins.add(FRONTEND_ORIGIN.rstrip("/"))
    return origins


def validate_redirect_uri(redirect_uri: str) -> str | None:
    """
    Validate redirect_uri against whitelist.
    Returns the validated redirect_uri or None if invalid.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(redirect_uri)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin in get_allowed_origins():
            return redirect_uri
    except Exception:
        pass
    return None


@router.get(
    "/google",
    summary="Initiate Google OAuth login",
    description="Redirects the user to Google's OAuth consent page. After authentication, Google redirects to the specified redirect_uri.",
    responses={
        302: {"description": "Redirect to Google OAuth consent page"},
        400: {"description": "Invalid redirect_uri"},
    },
)
async def google_login(request: Request, redirect_uri: str | None = None):
    """
    Start the Google OAuth login flow.

    This endpoint redirects users to Google's OAuth consent page where they
    can authorize the application to access their profile and email.

    The redirect_uri must be from an allowed origin (localhost:3000 or FRONTEND_ORIGIN).
    If not provided, defaults to {FRONTEND_ORIGIN}/auth/callback.
    """
    from fastapi import HTTPException, status

    if redirect_uri is None:
        redirect_uri = f"{FRONTEND_ORIGIN}/auth/callback"

    validated_uri = validate_redirect_uri(redirect_uri)
    if not validated_uri:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid redirect_uri. Allowed origins: {get_allowed_origins()}",
        )

    return await oauth.google.authorize_redirect(request, validated_uri)


@router.post(
    "/google/token",
    response_model=Response[AuthStatus],
    summary="Exchange Google authorization code for auth token",
    description="Frontend calls this endpoint with the authorization code received from Google OAuth callback.",
    responses={
        200: {
            "description": "Code exchange successful",
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
                        "existing_user": {
                            "summary": "Existing user (use signin)",
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
        400: {"description": "Invalid authorization code or OAuth error"},
    },
)
async def google_token_exchange(
    request: GoogleTokenRequest, db: Session = Depends(get_db)
):
    """
    Exchange Google authorization code for an auth token.

    This endpoint is called by the frontend after receiving the authorization
    code from Google OAuth callback. It exchanges the code for user info and
    returns an auth_token for subsequent signin/signup.

    Flow:
    1. Frontend initiates OAuth (user clicks login)
    2. Google redirects to frontend with `code`
    3. Frontend calls this endpoint with `code` and `redirect_uri`
    4. Backend exchanges code for user info
    5. Backend returns `auth_token` with status

    The auth_token is valid for 10 minutes.
    """
    import httpx
    from fastapi import HTTPException, status

    # Exchange code for tokens with Google
    token_url = "https://oauth2.googleapis.com/token"
    token_data = {
        "code": request.code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": request.redirect_uri,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        try:
            token_response = await client.post(token_url, data=token_data)
            if token_response.status_code != 200:
                logger.error(f"Google token exchange failed: {token_response.text}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code",
                )
            tokens = token_response.json()
        except httpx.RequestError as e:
            logger.error(f"Google token request error: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to connect to Google",
            )

    # Get user info from Google
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No ID token received from Google",
        )

    # Decode ID token to get user info (Google's ID tokens are JWTs)
    try:
        # We don't verify the signature here since we just received it from Google
        # In production, you might want to verify using Google's public keys
        user_info = jwt.decode(
            id_token,
            "",
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_at_hash": False,
            }
        )
    except Exception as e:
        logger.error(f"Failed to decode ID token: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to decode user information",
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
