# app/config/cookies.py
"""
Cookie settings for HTTP cookie-based authentication.
"""

from app.config.secrets import ENV, JWT_EXPIRE_HOURS

ACCESS_TOKEN_COOKIE_NAME = "waffice_access_token"


def get_cookie_settings() -> dict:
    """
    Get cookie settings based on environment.
    - Local: Secure=False, SameSite=Lax (for localhost development)
    - Dev/Prod: Secure=True, SameSite=None (for cross-origin requests)
    """
    max_age = JWT_EXPIRE_HOURS * 60 * 60  # Convert hours to seconds

    if ENV == "local":
        return {
            "key": ACCESS_TOKEN_COOKIE_NAME,
            "httponly": True,
            "secure": False,
            "samesite": "lax",
            "max_age": max_age,
            "path": "/",
        }

    # Dev/Prod: HTTPS required, SameSite=Lax for CSRF protection
    return {
        "key": ACCESS_TOKEN_COOKIE_NAME,
        "httponly": True,
        "secure": True,
        "samesite": "lax",
        "max_age": max_age,
        "path": "/",
    }
