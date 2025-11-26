# tests/test_auth_jwt.py

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.utils.jwt_auth import create_access_token, get_current_user


def test_jwt_round_trip():
    """
    create_access_token 으로 만든 토큰이 get_current_user 로 잘 해석되는지 확인
    """

    app = FastAPI()

    @app.get("/me")
    async def me(payload=Depends(get_current_user)):
        return payload

    token = create_access_token({"sub": "123", "user_id": 123})

    client = TestClient(app)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["sub"] == "123"
    assert body["user_id"] == 123
