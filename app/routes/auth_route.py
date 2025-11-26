# app/routes/auth_route.py

import os
from typing import Any, Dict

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_db
from app.controllers.user_controller import UserController
from app.utils.jwt_auth import create_access_token, get_current_user

# =========================
# CONFIG
# =========================

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET must be set")

# =========================
# OAUTH & ROUTER
# =========================

oauth = OAuth()
oauth.register(
    "google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter(prefix="/auth", tags=["auth"])


# =========================
# ROUTES
# =========================


@router.get(
    "/google/login",
    summary="Google OAuth 로그인 시작",
    description=(
        "Google OAuth 2.0 Login Flow를 시작\n"
        "- 사용자를 Google 로그인/동의 화면으로 리다이렉트\n"
        "- Callback to: `/auth/google/callback`"
    ),
)
async def google_login(request: Request):
    redirect_uri = request.url_for("google_auth_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get(
    "/google/callback",
    name="google_auth_callback",
    summary="Google OAuth 콜백 처리",
    description=(
        "Google OAuth 2.0 콜백을 처리 엔드포인트\n\n"
        "동작:\n"
        "1. Acc token 및 google_id 조회\n"
        "2. 얻은 `google_id`로 user 상태 조회 (`approved/pending/unregistered`).\n"
        "3a. 승인된 유저(`approved`)인 경우:\n"
        "   - `user_id` 기반으로 JWT acc token 발급\n"
        "   - `/auth/callback?status=approved&token=...` 으로 redirect.\n"
        "3b. 그 외(`pending`/`unregistered`)인 경우:\n"
        "   - 토큰을 발급하지 않습니다.\n"
        "   - `/auth/callback?status=...&google_id=...` 으로 redirect."
    ),
)
async def google_callback(request: Request, db: Session = Depends(get_db)):
    token = await oauth.google.authorize_access_token(request)

    userinfo = token.get("userinfo")
    if not userinfo:
        userinfo = await oauth.google.parse_id_token(request, token)

    if not userinfo:
        raise HTTPException(status_code=400, detail="Google login failed")

    google_sub = userinfo["sub"]
    email = userinfo.get("email")
    name = userinfo.get("name")
    picture = userinfo.get("picture")

    status_info = UserController.get_status(db, google_sub)
    status_str = status_info["status"]

    if status_str == "approved":
        user_id = status_info["user_id"]

        claims: Dict[str, Any] = {
            "sub": str(user_id),
            "user_id": user_id,
            "google_id": google_sub,
            "email": email,
            "name": name,
            "picture": picture,
            "provider": "google",
        }

        access_token = create_access_token(claims)
        redirect_url = (
            f"{FRONTEND_ORIGIN}/auth/callback" f"?status=approved&token={access_token}"
        )
    else:
        redirect_url = (
            f"{FRONTEND_ORIGIN}/auth/callback"
            f"?status={status_str}&google_id={google_sub}"
        )

    return RedirectResponse(url=redirect_url)
