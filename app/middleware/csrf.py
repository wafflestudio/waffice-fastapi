# app/middleware/csrf.py
"""
CSRF protection middleware.

Uses custom header requirement pattern:
- State-changing requests (POST, PUT, DELETE, PATCH) must include X-Requested-With header
- This prevents CSRF attacks because browsers won't send custom headers in cross-origin
  requests without a CORS preflight, and the preflight will fail for malicious origins
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Endpoints that don't require CSRF protection (e.g., OAuth callbacks)
CSRF_EXEMPT_PATHS = {
    "/auth/google",  # OAuth redirect endpoint
    "/docs",
    "/redoc",
    "/openapi.json",
}

# TODO: 프론트가 모든 POST 요청에 X-Requested-With를 보내도록 통일되면 이 예외를 제거한다.
CSRF_EXEMPT_EXACT_PATHS = {
    "/certificates/preview",
    "/certificates/drafts/preview",
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Middleware that requires X-Requested-With header for state-changing requests.

    This protects against CSRF attacks when using cookies with SameSite=None,
    because browsers won't include custom headers in cross-origin requests
    without a successful CORS preflight check.
    """

    async def dispatch(self, request: Request, call_next):
        # Skip CSRF check for safe methods
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # Skip CSRF check for exempt paths
        # TODO: CSRF_EXEMPT_EXACT_PATHS 제거 시 정확 경로 검사도 함께 제거한다.
        if request.url.path in CSRF_EXEMPT_EXACT_PATHS or any(
            request.url.path.startswith(path) for path in CSRF_EXEMPT_PATHS
        ):
            return await call_next(request)

        # Require X-Requested-With header for state-changing requests
        if not request.headers.get("X-Requested-With"):
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "error": "CSRF_VALIDATION_FAILED",
                    "message": "Missing X-Requested-With header",
                },
            )

        return await call_next(request)
