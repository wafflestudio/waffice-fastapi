from fastapi import FastAPI

from app import models
from app.config.database import Base, engine
from app.routes import user_route

app = FastAPI()

Base.metadata.create_all(bind=engine)

app.include_router(user_route.router)
