from fastapi import FastAPI

from app.config import Base, engine
from app.routes import user_route

Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(user_route.router)
