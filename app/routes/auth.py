import logging
from datetime import datetime, timedelta, timezone

# Google OAuth configuration
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request, Response as FastAPIResponse
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config.cookies import ACCESS_TOKEN_COOKIE_NAME, get_cookie_settings
from app.config.database import get_db
from app.config.secrets import (
    BOOTSTRAP_ADMIN_EMAIL,
    ENV,
    FRONTEND_ORIGIN,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    JWT_EXPIRE_HOURS,
    JWT_SECRET_KEY,
)
from app.deps.auth import JWT_ALGORITHM, get_current_user
from app.exceptions import (
    EmailAlreadyInUseError,
    GoogleAccountAlreadyLinkedError,
    InvalidAuthTokenError,
    StudentIdAlreadyInUseError,
    StudentIdNameMismatchError,
    UserNotRegisteredError,
)
from app.models import AuditAction, MemberRole, Qualification, User
from app.schemas import (
    AuthResult,
    AuthStatus,
    DevSigninRequest,
    GoogleTokenRequest,
    Response,
    SigninRequest,
    SignupRequest,
)
from app.services import AuditLogService, MemberService, ProjectService, UserService
from app.utils.text import normalize_text

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

# Separate router for dev-only endpoints (conditionally included in main.py)
dev_router = APIRouter()


def set_auth_cookie(response: FastAPIResponse, access_token: str) -> None:
    """Set authentication cookie on response."""
    settings = get_cookie_settings()
    response.set_cookie(value=access_token, **settings)


def clear_auth_cookie(response: FastAPIResponse) -> None:
    """Clear authentication cookie from response."""
    settings = get_cookie_settings()
    response.delete_cookie(
        key=settings["key"],
        path=settings["path"],
        secure=settings["secure"],
        httponly=settings["httponly"],
        samesite=settings["samesite"],
    )


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


def grant_bootstrap_superadmin(db: Session, user: User, verified_email: str) -> User:
    """Grant the configured break-glass account after Google verifies its email."""
    if not BOOTSTRAP_ADMIN_EMAIL or verified_email.casefold() != BOOTSTRAP_ADMIN_EMAIL:
        return user

    changes = {
        field: {"from": getattr(user, field), "to": value}
        for field, value in (
            ("is_superadmin", True),
            ("is_admin", True),
            ("qualification", Qualification.ACTIVE),
        )
        if getattr(user, field) != value
    }
    if not changes:
        return user

    user.is_superadmin = True
    user.is_admin = True
    user.qualification = Qualification.ACTIVE
    AuditLogService.log(
        db,
        user_id=user.id,
        action=AuditAction.ROLE_CHANGED,
        payload={"source": "bootstrap_verified_email", **changes},
    )
    db.commit()
    db.refresh(user)
    logger.warning("Granted bootstrap superadmin privileges to user_id=%s", user.id)
    return user


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

    return await oauth.google.authorize_redirect(request, redirect_uri=validated_uri)


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
    import sys

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

    print(
        f"[AUTH] Google token exchange request: redirect_uri={request.redirect_uri}",
        flush=True,
    )

    async with httpx.AsyncClient() as client:
        try:
            token_response = await client.post(token_url, data=token_data)
            print(
                f"[AUTH] Google token response status: {token_response.status_code}",
                flush=True,
            )
            if token_response.status_code != 200:
                print(
                    f"[AUTH] Google token exchange failed: {token_response.text}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to exchange authorization code: {token_response.text}",
                )
            tokens = token_response.json()
        except httpx.RequestError as e:
            print(f"[AUTH] Google token request error: {e}", flush=True)
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

    # Verify and decode ID token using Google's public keys
    try:
        print("[AUTH] Importing google.auth modules...", flush=True)
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token

        print("[AUTH] Verifying ID token with Google", flush=True)
        user_info = google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            GOOGLE_CLIENT_ID,
        )
        print(f"[AUTH] ID token verified, email={user_info.get('email')}", flush=True)
    except Exception as e:
        print(f"[AUTH] Failed to verify ID token: {type(e).__name__}: {e}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to decode user information: {e}",
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
    "/google/relink",
    response_model=Response[AuthResult],
    summary="Relink current user to a new Google account",
    description="Replace the current user's Google login identifier and email using a temporary OAuth auth token.",
    responses={
        200: {"description": "Google account relinked successfully"},
        400: {"description": "Invalid auth token"},
        401: {"description": "Not authenticated"},
        409: {"description": "Google account or email already linked to another user"},
    },
)
async def relink_google_account(
    request: SigninRequest,
    response: FastAPIResponse,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Relink the authenticated user to the Google account represented by auth_token.

    The auth_token is produced by `/auth/google/token` after the user completes
    OAuth with the new Google account. Both google_id and email are updated
    together so future login attempts resolve to this user.
    """
    payload = decode_auth_token(request.auth_token)
    google_id = payload["google_id"]
    email = payload["email"]

    existing_google_user = UserService.get_by_google_id(db, google_id)
    if existing_google_user and existing_google_user.id != current_user.id:
        raise GoogleAccountAlreadyLinkedError()

    existing_email_user = UserService.get_by_email(db, email)
    if existing_email_user and existing_email_user.id != current_user.id:
        raise EmailAlreadyInUseError()

    user = current_user
    if user.google_id != google_id or user.email != email:
        user = UserService.update(db, user, google_id=google_id, email=email)

    access_token = create_access_token(user.id, user.email, user.google_id)
    set_auth_cookie(response, access_token)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            user=user,
        ),
    )


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
async def signin(
    request: SigninRequest,
    response: FastAPIResponse,
    db: Session = Depends(get_db),
):
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

    user = grant_bootstrap_superadmin(db, user, email)

    # Generate JWT
    access_token = create_access_token(user.id, user.email, user.google_id)

    # Set auth cookie
    set_auth_cookie(response, access_token)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
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
        409: {"description": "Student ID already belongs to a registered user"},
    },
)
async def signup(
    request: SignupRequest,
    response: FastAPIResponse,
    db: Session = Depends(get_db),
):
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

    if not user:
        deleted_by_google_id, deleted_by_email = UserService.get_deleted_by_identity(
            db, google_id, email
        )
        if (
            deleted_by_google_id
            and deleted_by_email
            and deleted_by_google_id.id != deleted_by_email.id
        ):
            raise GoogleAccountAlreadyLinkedError()
        deleted_user = deleted_by_google_id or deleted_by_email
        if deleted_user:
            user = UserService.restore(db, deleted_user)

    if user:
        # User already exists - return existing user (idempotency)
        if not user.google_id:
            UserService.update(db, user, google_id=google_id)
    else:
        signup_data = dict(
            google_id=google_id,
            email=email,
            name=request.name,
            generation=request.generation,
            student_id=request.student_id,
            graduation_status=request.graduation_status,
            requested_qualification=request.qualification,
            contact_email=str(request.email),
            privacy_policy_agreed=request.privacy_policy_agreed,
            terms_agreed=request.terms_agreed,
            email_notifications_agreed=request.email_notifications_agreed,
            sms_notifications_agreed=request.sms_notifications_agreed,
            phone=request.phone,
            affiliation=request.affiliation,
            bio=request.bio,
            github_username=request.github_username,
            qualification=Qualification.PENDING,
        )
        student_user = UserService.get_by_student_id(db, request.student_id)
        if student_user:
            if not student_user.is_temporary:
                raise StudentIdAlreadyInUseError()
            if normalize_text(student_user.name) != normalize_text(request.name):
                raise StudentIdNameMismatchError()
            user = UserService.update(
                db,
                student_user,
                **signup_data,
                is_temporary=False,
            )
        else:
            user = UserService.create(db, **signup_data)

    user = grant_bootstrap_superadmin(db, user, email)

    # Generate JWT
    access_token = create_access_token(user.id, user.email, user.google_id)

    # Set auth cookie
    set_auth_cookie(response, access_token)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
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

    Note: Token is NOT refreshed here to prevent unlimited session extension.
    Users must re-authenticate when their token expires.
    """
    if current_user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            user=current_user,
        ),
    )


@router.post(
    "/logout",
    response_model=Response[None],
    summary="Logout user",
    description="Clear authentication cookie to logout user.",
    responses={
        200: {"description": "Logout successful"},
    },
)
async def logout(response: FastAPIResponse):
    """
    Logout the current user by clearing the authentication cookie.
    """
    clear_auth_cookie(response)
    return Response(ok=True, data=None)


def _grant_admin_team_membership(
    db: Session, user: User, *, is_admin: bool, is_president: bool
) -> None:
    """Dev-only shortcut: reflect is_admin/is_president by directly adding,
    changing, or removing this user's 운영팀 (admin team) membership, then
    resyncing -- rather than setting those derived columns directly.

    Passes enforce_guards=False to MemberService.remove/change: the "only
    the sitting president may appoint a new leader" rule is an HTTP-route-
    level check (not enforced at the service layer this calls into), but the
    "can't remove/demote yourself or the last leader" guards on
    remove/change don't make sense for this trusted, non-actor-gated
    bootstrap tool (it always acts on the signing-in user themselves, so
    those guards would otherwise always fire) -- audit logging still runs
    normally either way, so leadership history stays consistent for
    certificate_render._build_executive_rows. No-ops if the 운영팀 project
    hasn't been bootstrapped yet.
    """
    admin_team = ProjectService.get_admin_team_project(db)
    if admin_team is None:
        return

    desired_role = (
        MemberRole.LEADER if is_president else MemberRole.MEMBER if is_admin else None
    )
    existing = MemberService.get_active(db, admin_team.id, user.id)

    if desired_role is None:
        if existing is not None:
            MemberService.remove(
                db, member=existing, actor_id=user.id, enforce_guards=False
            )
    elif existing is None:
        MemberService.add(
            db,
            project_id=admin_team.id,
            user_id=user.id,
            role=desired_role,
            position=None,
            actor_id=user.id,
        )
    elif existing.role != desired_role:
        MemberService.change(
            db,
            member=existing,
            actor_id=user.id,
            role=desired_role,
            enforce_guards=False,
        )

    ProjectService.sync_admin_team_roles(db)
    db.commit()


@dev_router.post(
    "/signin-dev",
    response_model=Response[AuthResult],
    summary="Development-only signin",
    description="Sign in with mock credentials for testing. Only available in local/dev environments.",
    responses={
        200: {"description": "Signin successful"},
    },
)
async def signin_dev(
    request: DevSigninRequest,
    response: FastAPIResponse,
    db: Session = Depends(get_db),
):
    """
    Development-only signin endpoint for testing without Google OAuth.

    This endpoint allows signing in with any email/name combination for testing purposes.
    It creates a new user if one doesn't exist, or updates an existing user's
    qualification/is_leader.

    is_admin/is_president are derived from 운영팀 (admin team) project
    membership (see ProjectService.sync_admin_team_roles) -- rather than
    setting those columns directly, this endpoint adds/updates/removes the
    user's 운영팀 membership accordingly (see _grant_admin_team_membership),
    so the result matches what actually granting them through the projects
    API would look like.

    This router is only included in local/dev environments (see main.py).
    """
    from fastapi import HTTPException, status

    # Map qualification string to enum
    qualification_map = {
        "pending": Qualification.PENDING,
        "associate": Qualification.ASSOCIATE,
        "regular": Qualification.REGULAR,
        "active": Qualification.ACTIVE,
    }
    qualification = qualification_map[request.qualification]

    # Check for existing user by email
    user = UserService.get_by_email(db, request.email)

    if user:
        # Update existing user's is_leader and qualification
        UserService.update(
            db,
            user,
            is_leader=request.is_leader,
            qualification=qualification,
        )
    else:
        # Create new user with dev google_id
        # Handle race condition: if concurrent request created user, catch and retry
        from sqlalchemy.exc import IntegrityError

        dev_google_id = f"dev_{request.email}"
        try:
            user = UserService.create(
                db,
                google_id=dev_google_id,
                email=request.email,
                name=request.name,
                qualification=qualification,
                is_leader=request.is_leader,
            )
        except IntegrityError:
            db.rollback()
            user = UserService.get_by_email(db, request.email)
            if user:
                UserService.update(
                    db,
                    user,
                    is_leader=request.is_leader,
                    qualification=qualification,
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to create or find user",
                )

    _grant_admin_team_membership(
        db, user, is_admin=request.is_admin, is_president=request.is_president
    )

    # Generate JWT
    access_token = create_access_token(user.id, user.email, user.google_id)

    # Set auth cookie
    set_auth_cookie(response, access_token)

    if user.qualification == Qualification.PENDING:
        auth_status = "pending"
    else:
        auth_status = "active"

    return Response(
        ok=True,
        data=AuthResult(
            status=auth_status,
            user=user,
        ),
    )
