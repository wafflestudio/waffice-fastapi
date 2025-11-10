# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

import app.config as config
import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.create_all()
    yield


app = FastAPI(lifespan=lifespan)

from app.routes import user_route, userhist_route

app.include_router(user_route.router)
app.include_router(userhist_route.router)


@app.get("/health")
def health():
    return {"ok": True}
