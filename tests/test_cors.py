from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.middleware import CSRFMiddleware


def test_csrf_rejection_keeps_cors_headers():
    origin = "https://waffice.wafflestudio.com"
    test_app = FastAPI()
    test_app.add_middleware(CSRFMiddleware)
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    response = TestClient(test_app).post("/protected", headers={"Origin": origin})

    assert response.status_code == 403
    assert response.json()["error"] == "CSRF_VALIDATION_FAILED"
    assert response.headers["access-control-allow-origin"] == origin
    assert response.headers["access-control-allow-credentials"] == "true"


def test_only_certificate_previews_are_csrf_exempt():
    test_app = FastAPI()

    @test_app.post("/{path:path}")
    async def post_endpoint(path: str):
        return {"path": path}

    test_app.add_middleware(CSRFMiddleware)
    client = TestClient(test_app)

    assert client.post("/certificates/preview").status_code == 200
    assert client.post("/certificates/drafts/preview").status_code == 200
    assert client.post("/certificates").status_code == 403
    assert client.post("/certificates/drafts").status_code == 403
    assert client.post("/certificates/preview-copy").status_code == 403
