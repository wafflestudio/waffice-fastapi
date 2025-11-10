# tests/test_pending_user.py

import sys

print("PYTHONPATH:", sys.path[:3])

import pytest
from fastapi.testclient import TestClient

from app.config.database import create_all, drop_all
from app.main import app

client = TestClient(app)


# ------------------------------------------------------------------------------
# DB RESET PER TEST
# ------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_db():
    """
    Reset database before each test so cases don't affect each other.
    Uses helpers exposed in app.config.database.
    """
    drop_all()
    create_all()
    yield


# ------------------------------------------------------------------------------
# BASIC HEALTH TEST
# ------------------------------------------------------------------------------
def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


# ------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------
def _create_pending(google_id: str, email: str, name: str, github: str | None = None):
    payload = {
        "google_id": google_id,
        "email": email,
        "name": name,
    }
    if github is not None:
        payload["github"] = github
    return client.post("/api/user/create", json=payload)


def _get_status(google_id: str):
    return client.get("/api/user/status", params={"google_id": google_id})


def _decide(google_id: str, decision: str, **extra):
    """
    decision: "accept" or "deny"
    For accept, you may need to pass type="programmer|designer", privilege="associate|regular|active"
    """
    payload = {"google_id": google_id, "decision": decision}
    payload.update(extra)
    return client.post("/api/exct/user/decide", json=payload)


# ------------------------------------------------------------------------------
# PENDING USER TESTS
# ------------------------------------------------------------------------------
def test_pending_user_create_ok():
    """
    pending 유저가 제대로 만들어지는지
    """
    r = _create_pending("gid-1", "u1@example.com", "U1", github="u1gh")
    assert r.status_code in (200, 201)
    body = r.json()
    # 생성 응답에 최소한 google_id와 id(or ctime) 중 하나는 있어야 한다고 가정
    assert body.get("google_id") == "gid-1"
    assert any(k in body for k in ("id", "ctime"))

    # 상태가 pending 인지 확인
    s = _get_status("gid-1")
    assert s.status_code == 200
    status = s.json().get("status")
    assert status in ("pending", "applied", "waiting")  # 구현 명칭 차이 허용


def test_pending_user_duplicate_not_allowed():
    """
    중복된 pending 유저를 만드는게 불가능한지
    """
    r1 = _create_pending("gid-dup", "dup@example.com", "Dup")
    assert r1.status_code in (200, 201)

    r2 = _create_pending("gid-dup", "dup2@example.com", "Dup2")
    # 중복이면 보통 400/409 등을 반환
    assert r2.status_code in (400, 409, 422)


def test_pending_user_create_different_id_allowed():
    """
    pending user 가 있는 상태에서, 다른 id로 pending user를 만드는게 가능한지
    """
    r1 = _create_pending("gid-a", "a@example.com", "A")
    r2 = _create_pending("gid-b", "b@example.com", "B")

    assert r1.status_code in (200, 201)
    assert r2.status_code in (200, 201)

    s1 = _get_status("gid-a")
    s2 = _get_status("gid-b")
    assert s1.status_code == 200 and s2.status_code == 200
    assert s1.json().get("status") in ("pending", "applied", "waiting")
    assert s2.json().get("status") in ("pending", "applied", "waiting")


def test_pending_user_accept_flow():
    """
    accept가 잘 되는지
    - pending 생성 → accept 결정 → status가 approved/active 로 바뀌는지
    """
    gid = "gid-accept"
    r = _create_pending(gid, "acc@example.com", "ACC", github="accgh")
    assert r.status_code in (200, 201)

    # 승인 결정 (type/privilege는 요구사항에 맞게 조정)
    d = _decide(gid, "accept", type="programmer", privilege="associate")
    assert d.status_code in (200, 201)

    # 승인 후 상태 확인
    s = _get_status(gid)
    assert s.status_code == 200
    st = s.json().get("status")
    # 구현 명칭 차이를 허용: approved/active/ok 등
    assert st in ("approved", "active", "ok")

    # (선택) JWT 토큰 발급되는 경우 토큰 존재 여부까지 확인
    # token = s.json().get("token")
    # assert token is None or isinstance(token, str)


def test_pending_user_deny_flow():
    """
    deny가 잘 되는지
    - pending 생성 → deny 결정 → status가 none/denied 로 바뀌는지
    """
    gid = "gid-deny"
    r = _create_pending(gid, "deny@example.com", "DENY")
    assert r.status_code in (200, 201)

    d = _decide(gid, "deny")
    # 보통 200/204/201 등 다양하게 가능
    assert d.status_code in (200, 201, 204)

    s = _get_status(gid)
    assert s.status_code == 200
    st = s.json().get("status")
    assert st in ("unregistered", "denied")
