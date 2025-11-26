# tests/test_auth_route.py

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


class DummyOAuthGoogle:
    async def authorize_access_token(self, request):
        return {
            "userinfo": {
                "sub": "gid-accept",
                "email": "acc@example.com",
                "name": "ACC",
                "picture": "https://example.com/acc.png",
            }
        }

    async def parse_id_token(self, request, token):
        return token["userinfo"]


@pytest.fixture(autouse=True)
def _patch_oauth_google(monkeypatch):
    # auth_route.oauth.google 을 DummyOAuthGoogle 인스턴스로 교체
    import app.routes.auth_route as auth_route

    dummy = DummyOAuthGoogle()
    monkeypatch.setattr(auth_route.oauth, "google", dummy)
    yield


def test_google_callback_pending_or_unregistered():
    """
    아직 approved 가 아닌 상태에서 /auth/google/callback 을 치면
    status와 google_id 쿼리스트링으로 리다이렉트하는지 확인
    (get_status 결과를 pending/unregistered 로 맞춰 놓으면 됨)
    """
    # gid-accept 에 대한 상태는 기본적으로 unregistered 이므로
    resp = client.get("/auth/google/callback", follow_redirects=False)

    assert resp.status_code in (302, 307)
    loc = resp.headers["Location"]
    # /auth/callback?status=...&google_id=gid-accept 형태인지 검사
    assert "/auth/callback" in loc
    assert "google_id=gid-accept" in loc
