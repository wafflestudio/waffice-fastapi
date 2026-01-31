# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

import app.config as config
import app.models
from app.config.secrets import APP_SECRET_KEY, ENV, FRONTEND_ORIGIN


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.run_migrations()
    yield


app = FastAPI(lifespan=lifespan)

# ==============================
# CORS / SESSION (OAuth 용)
# ==============================
# CORS origins 설정
if ENV in ["local", "dev"]:
    # 개발 환경에서는 localhost:3000 허용
    allowed_origins = [
        "http://localhost:3000",
        FRONTEND_ORIGIN,
    ]
else:
    # Production 환경에서는 실제 도메인만 허용
    allowed_origins = [FRONTEND_ORIGIN]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF protection - requires X-Requested-With header for state-changing requests
from app.middleware import CSRFMiddleware

app.add_middleware(CSRFMiddleware)

# Google OAuth 에서 state, code 저장할 세션
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)


# ==============================
# EXCEPTION HANDLERS
# ==============================
from fastapi import Request
from fastapi.responses import JSONResponse

from app.exceptions import AppError


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.code, "message": exc.message},
    )


# ==============================
# ROUTERS
# ==============================
from app.routes import auth, projects, upload, users

app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(users.router, prefix="/users", tags=["Users"])
app.include_router(projects.router, prefix="/projects", tags=["Projects"])
app.include_router(upload.router, prefix="/upload", tags=["Upload"])


# ==============================
# HEALTH CHECK
# ==============================
@app.get("/health-check")
def health_check():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}
