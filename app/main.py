# app/main.py
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

import app.config as config
import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.create_all()
    yield


app = FastAPI(lifespan=lifespan)

# ==============================
# CORS / SESSION (OAuth 용)
# ==============================
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")
APP_SECRET_KEY = os.getenv("APP_SECRET_KEY", "I hate math")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Google OAuth 에서 state, code 저장할 세션
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET_KEY)


# ==============================
# ROUTERS
# ==============================
from app.routes import auth_route, project_route, user_route, userhist_route

app.include_router(user_route.router)
app.include_router(userhist_route.router)
app.include_router(auth_route.router)
app.include_router(project_route.router)


# ==============================
# HEALTH CHECK
# ==============================
@app.get("/health-check")
def health_check():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}
