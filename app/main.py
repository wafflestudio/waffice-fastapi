from fastapi import FastAPI

from app import models
from app.config.database import Base, engine
from app.routes import user_route, userhist_route

app = FastAPI()

Base.metadata.create_all(bind=engine)


@app.get("/health-check")
def health_check():
    return {"ok": True}


app.include_router(user_route.router)
app.include_router(userhist_route.router)
