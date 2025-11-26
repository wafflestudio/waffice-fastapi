# app/utils/jwt_auth.py

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

# =========================
# CLAIM OBJECT
# =========================
# claims: Dict[str, Any] = {
#     "sub": str(user_id),
#     "user_id": user_id,
#     "google_id": google_sub,
#     "email": email,
#     "name": name,
#     "picture": picture,
#     "provider": "google",
# }
# =========================

# =========================
# JWT CONFIG
# =========================

JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.getenv("APP_SECRET_KEY", "change-me"))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "2"))

# Authorization: Bearer <token> 에서 토큰 뽑아오는 dependency
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token-not-used")

# =========================
# JWT HELPERS
# =========================


def create_access_token(
    claims: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """JWT access token 생성"""
    now = datetime.now(timezone.utc)
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRE_HOURS)
    exp = now + expires_delta

    payload: Dict[str, Any] = {
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        **claims,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    """헤더의 Bearer 토큰을 디코드해서 payload(dict)를 반환"""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            raise cred_exc
    except JWTError:
        raise cred_exc
    return payload
