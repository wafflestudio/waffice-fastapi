"""Tests for the president / signature API (활동증명서용 회장 서명 등록/변경 +
회장 임기 관리).

Covers `app/routes/certificates.py` and `app/services/certificate.py`
(`SignatureService` / `PresidentService`) end-to-end against a real
testcontainers MySQL 8 database. Object storage is mocked the way
`tests/test_member_detail.py` mocks it:
`monkeypatch.setattr("app.routes.certificates.OCIObjectStorageService", ...)`.
"""

import base64
import threading
from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import (
    PresidentAppointmentConflictError,
    SignatureUploadConflictError,
)
from app.models import CertificateSignature, PresidentTerm, User
from app.services.certificate import PresidentService, SignatureService

pytestmark = pytest.mark.usefixtures("fake_storage")

# A real (tiny, 1x1 transparent) PNG.
VALID_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF-"


def _make_image_bytes(image_format: str) -> bytes:
    """A tiny (4x4) *real* image in the given Pillow format -- these must be
    bytes an actual image decoder would accept, not just bytes that happen to
    start with the right magic number, so the signature-upload magic-byte
    check is exercised against genuine files."""
    buf = BytesIO()
    Image.new("RGB", (4, 4), color=(10, 20, 30)).save(buf, format=image_format)
    return buf.getvalue()


# Real (tiny) images in each newly-accepted format, for signature uploads.
VALID_JPEG_BYTES = _make_image_bytes("JPEG")
VALID_WEBP_BYTES = _make_image_bytes("WEBP")
VALID_GIF_BYTES = _make_image_bytes("GIF")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload_signature(
    client: TestClient,
    token: str,
    *,
    body: bytes = VALID_PNG_BYTES,
    content_type="image/png",
):
    return client.put(
        "/certificates/signature/me",
        files={"file": ("signature.png", body, content_type)},
        headers=_auth(token),
    )


# ---------------------------------------------------------------------------
# Object storage mock: in-memory dict shared across the requests of a single
# test (so an upload in one call is readable by `get_bytes` in another).
#
# ⑤ uses `OCIObjectStorageService()` directly in the route (not the
# `create_object_storage()` factory from PR_0), so the mock patches the class
# constructor the route imports.
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> dict:
    data: dict[str, bytes] = {}

    class FakeObjectStorage:
        def upload_bytes(self, object_name: str, body: bytes, content_type: str) -> str:
            data[object_name] = body
            return f"https://fake.local/{object_name}"

        def get_bytes(self, object_name: str) -> bytes:
            return data[object_name]

        def delete_object(self, object_name: str) -> None:
            data.pop(object_name, None)

    monkeypatch.setattr(
        "app.routes.certificates.OCIObjectStorageService", FakeObjectStorage
    )
    return data


class TestSignatureUpload:
    """GET/PUT /certificates/signature/me (president only)."""

    def test_non_president_admin_cannot_access(
        self, client: TestClient, admin_token: str
    ):
        response = client.get("/certificates/signature/me", headers=_auth(admin_token))
        assert response.status_code == 403

    def test_get_signature_when_none_registered(
        self,
        client: TestClient,
        president_token: str,
        open_president_term: PresidentTerm,
    ):
        response = client.get(
            "/certificates/signature/me", headers=_auth(president_token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"] is None
        assert body["message"] == "등록된 서명이 없습니다."

    def test_upload_rejects_unsupported_content_type(
        self, client: TestClient, president_token: str, open_president_term
    ):
        """A genuinely non-image content-type (not in the PNG/JPEG/WebP/GIF
        allowlist) is rejected before the body is even magic-byte-checked."""
        response = _upload_signature(
            client,
            president_token,
            body=PDF_MAGIC + b"1.4 not an image at all",
            content_type="application/pdf",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_SIGNATURE_FILE"

    def test_upload_rejects_svg_content_type(
        self, client: TestClient, president_token: str, open_president_term
    ):
        """SVG is deliberately excluded from the allowlist -- it can embed
        scripts/external references, which is unsafe -- even though it is a
        common vector image format."""
        response = _upload_signature(
            client,
            president_token,
            body=b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            content_type="image/svg+xml",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_SIGNATURE_FILE"

    def test_upload_rejects_wrong_magic_bytes_even_with_png_content_type(
        self, client: TestClient, president_token: str, open_president_term
    ):
        """The content-type header alone is spoofable; the magic-byte check
        must independently reject a renamed non-PNG file."""
        response = _upload_signature(
            client,
            president_token,
            body=b"not-a-real-png-body",
            content_type="image/png",
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_SIGNATURE_FILE"

    def test_upload_rejects_spoofed_content_type_with_mismatched_real_image(
        self, client: TestClient, president_token: str, open_president_term
    ):
        """Declaring `image/jpeg` while uploading real PNG bytes must still
        be rejected -- each content-type is checked against its *own*
        format-specific magic bytes, not just "is this some kind of
        image"."""
        response = _upload_signature(
            client, president_token, body=VALID_PNG_BYTES, content_type="image/jpeg"
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_SIGNATURE_FILE"

    def test_upload_too_large(
        self, client: TestClient, president_token: str, open_president_term
    ):
        oversized = PNG_MAGIC + b"0" * (5 * 1024 * 1024 + 1)
        response = _upload_signature(client, president_token, body=oversized)
        assert response.status_code == 413
        assert response.json()["error"] == "SIGNATURE_FILE_TOO_LARGE"

    @pytest.mark.parametrize(
        "content_type,body,expected_ext",
        [
            ("image/png", VALID_PNG_BYTES, ".png"),
            ("image/jpeg", VALID_JPEG_BYTES, ".jpg"),
            ("image/webp", VALID_WEBP_BYTES, ".webp"),
            ("image/gif", VALID_GIF_BYTES, ".gif"),
        ],
    )
    def test_upload_accepts_each_allowed_format(
        self,
        client: TestClient,
        db: Session,
        president_token: str,
        president_user: User,
        open_president_term: PresidentTerm,
        fake_storage: dict,
        content_type: str,
        body: bytes,
        expected_ext: str,
    ):
        """PNG (regression), JPEG, WebP, and GIF -- each with a real image
        body of its own format -- are all accepted, and the stored
        object_key gets the matching extension."""
        response = _upload_signature(
            client, president_token, body=body, content_type=content_type
        )
        assert response.status_code == 200

        row = (
            db.query(CertificateSignature)
            .filter(CertificateSignature.user_id == president_user.id)
            .one()
        )
        assert row.object_key.endswith(expected_ext)
        assert row.object_key in fake_storage

    def test_upload_happy_path_and_replace(
        self,
        client: TestClient,
        db: Session,
        president_token: str,
        president_user: User,
        open_president_term: PresidentTerm,
        fake_storage: dict,
    ):
        first = _upload_signature(client, president_token)
        assert first.status_code == 200
        first_data = first.json()["data"]
        assert first_data["user_id"] == president_user.id

        first_row = (
            db.query(CertificateSignature)
            .filter(CertificateSignature.user_id == president_user.id)
            .one()
        )
        first_key = first_row.object_key
        assert first_key in fake_storage

        # Replace: same signature id, new object_key, old object deleted.
        second = _upload_signature(client, president_token)
        assert second.status_code == 200
        assert second.json()["data"]["id"] == first_data["id"]

        db.expire_all()
        assert (
            db.query(CertificateSignature)
            .filter(CertificateSignature.user_id == president_user.id)
            .count()
            == 1
        )
        second_row = (
            db.query(CertificateSignature)
            .filter(CertificateSignature.user_id == president_user.id)
            .one()
        )
        assert second_row.object_key != first_key
        assert first_key not in fake_storage
        assert second_row.object_key in fake_storage

        get_resp = client.get(
            "/certificates/signature/me", headers=_auth(president_token)
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["data"]["id"] == first_data["id"]

    def test_upsert_concurrent_first_upload_returns_clean_error_not_500(
        self, engine, president_user: User, monkeypatch: pytest.MonkeyPatch
    ):
        """Two requests racing to register the *first* signature for the
        same president both read `existing = None` via
        `SignatureService.get_by_user` before either commits, so both try to
        INSERT a new `CertificateSignature` row. The DB
        `uq_certificate_signatures_user_id` unique constraint correctly
        prevents two rows for the same user_id from ever being committed,
        but without exception handling around `db.commit()`, the losing
        transaction's `IntegrityError` would propagate unhandled --
        `app/main.py` only registers a handler for `AppError`, so it would
        surface as an unstructured 500 instead of a clean domain error.

        A second barrier pins both threads' `get_by_user` read together --
        without it, one thread's entire `upsert()` (including commit) can
        finish before the other even reads, in which case the second thread
        would see the first thread's committed row and take the *update*
        path instead of racing on INSERT, and there would be nothing to
        conflict on.
        """
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        start_barrier = threading.Barrier(2)
        read_barrier = threading.Barrier(2)
        original_get_by_user = SignatureService.get_by_user

        def synced_get_by_user(db, user_id):
            result = original_get_by_user(db, user_id)
            read_barrier.wait(timeout=10)
            return result

        monkeypatch.setattr(
            SignatureService, "get_by_user", staticmethod(synced_get_by_user)
        )

        results: list[str] = []
        results_lock = threading.Lock()

        class _NoopStorage:
            def delete_object(self, object_name: str) -> None:
                pass

        def worker(object_key: str) -> None:
            session = session_factory()
            try:
                start_barrier.wait(timeout=10)
                try:
                    SignatureService.upsert(
                        session,
                        user_id=president_user.id,
                        object_key=object_key,
                        storage=_NoopStorage(),
                    )
                    outcome = "ok"
                except SignatureUploadConflictError:
                    outcome = "conflict"
                with results_lock:
                    results.append(outcome)
            finally:
                session.close()

        t1 = threading.Thread(target=worker, args=("signatures/a.png",))
        t2 = threading.Thread(target=worker, args=("signatures/b.png",))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2
        assert results.count("ok") == 1, f"expected exactly one winner, got {results!r}"
        assert results.count("conflict") == 1

        verify_session = session_factory()
        try:
            count = (
                verify_session.query(CertificateSignature)
                .filter(CertificateSignature.user_id == president_user.id)
                .count()
            )
            assert count == 1
        finally:
            verify_session.close()


class TestPresidentTermAdministration:
    """POST/GET /certificates/president-terms (admin only)."""

    def test_appoint_closes_previous_open_term(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        active_user: User,
    ):
        first = client.post(
            "/certificates/president-terms",
            json={"user_id": regular_user.id, "started_at": "2025-01-01"},
            headers=_auth(admin_token),
        )
        assert first.status_code == 200
        first_term_id = first.json()["data"]["id"]

        second = client.post(
            "/certificates/president-terms",
            json={"user_id": active_user.id, "started_at": "2026-01-01"},
            headers=_auth(admin_token),
        )
        assert second.status_code == 200
        assert second.json()["data"]["ended_at"] is None
        assert second.json()["data"]["user"]["id"] == active_user.id

        db.expire_all()
        old_term = db.get(PresidentTerm, first_term_id)
        assert old_term.ended_at == date(2026, 1, 1)

        # DB invariant: exactly one open term.
        open_count = (
            db.query(PresidentTerm).filter(PresidentTerm.ended_at.is_(None)).count()
        )
        assert open_count == 1

    def test_get_current_president(
        self,
        client: TestClient,
        admin_token: str,
        president_user: User,
        open_president_term: PresidentTerm,
    ):
        response = client.get(
            "/certificates/president-terms/current", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        assert response.json()["data"]["user"]["id"] == president_user.id

    def test_get_current_president_when_none_appointed(
        self, client: TestClient, admin_token: str
    ):
        response = client.get(
            "/certificates/president-terms/current", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        assert response.json()["data"] is None

    def test_non_admin_cannot_appoint_president(
        self, client: TestClient, regular_token: str, active_user: User
    ):
        response = client.post(
            "/certificates/president-terms",
            json={"user_id": active_user.id, "started_at": "2026-01-01"},
            headers=_auth(regular_token),
        )
        assert response.status_code == 403

    def test_db_rejects_a_second_open_term_inserted_directly(
        self, db: Session, regular_user: User, active_user: User
    ):
        """Bypasses the service layer to prove the `uq_president_current`
        MySQL 8 generated-column unique index is the real backstop, not just
        `PresidentService.appoint`'s application-level close-then-open."""
        db.add(PresidentTerm(user_id=regular_user.id, started_at=date(2025, 1, 1)))
        db.commit()

        db.add(PresidentTerm(user_id=active_user.id, started_at=date(2025, 6, 1)))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    def test_appoint_concurrent_conflict_returns_clean_error_not_500(
        self, engine, regular_user: User, active_user: User
    ):
        """Two admins appointing different presidents at nearly the same
        instant both pass `PresidentService.appoint`'s in-transaction
        "close current, then open new" guard from their own snapshot. The DB
        `uq_president_current` unique constraint correctly prevents two open
        terms from ever being committed (atomicity holds), but without
        exception handling around `db.commit()`, the losing transaction's
        `IntegrityError` propagates unhandled -- and `app/main.py` only
        registers a handler for `AppError`, so it would surface as an
        unstructured 500 instead of a clean domain error.
        """
        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        barrier = threading.Barrier(2)
        results: list[tuple[str, int]] = []
        results_lock = threading.Lock()

        def worker(user_id: int) -> None:
            session = session_factory()
            try:
                barrier.wait()
                try:
                    term = PresidentService.appoint(
                        session, user_id=user_id, started_at=date(2026, 1, 1)
                    )
                    outcome = ("ok", term.user_id)
                except PresidentAppointmentConflictError:
                    outcome = ("conflict", user_id)
                with results_lock:
                    results.append(outcome)
            finally:
                session.close()

        t1 = threading.Thread(target=worker, args=(regular_user.id,))
        t2 = threading.Thread(target=worker, args=(active_user.id,))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2
        oks = [r for r in results if r[0] == "ok"]
        conflicts = [r for r in results if r[0] == "conflict"]
        assert len(oks) == 1, f"expected exactly one winner, got {results!r}"
        assert len(conflicts) == 1

        verify_session = session_factory()
        try:
            open_count = (
                verify_session.query(PresidentTerm)
                .filter(PresidentTerm.ended_at.is_(None))
                .count()
            )
            assert open_count == 1
        finally:
            verify_session.close()

    def test_appoint_rejects_started_at_before_current_term(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        active_user: User,
    ):
        first = client.post(
            "/certificates/president-terms",
            json={"user_id": regular_user.id, "started_at": "2026-01-01"},
            headers=_auth(admin_token),
        )
        assert first.status_code == 200

        second = client.post(
            "/certificates/president-terms",
            json={"user_id": active_user.id, "started_at": "2025-01-01"},
            headers=_auth(admin_token),
        )
        assert second.status_code == 400
        assert second.json()["error"] == "INVALID_PRESIDENT_TERM"

    def test_appoint_rejects_started_at_in_the_future(
        self, client: TestClient, admin_token: str, regular_user: User
    ):
        """Appointment takes effect immediately -- `require_president` /
        `PresidentService.get_current` only check `ended_at IS NULL`, not
        `started_at`. A future-dated `started_at` must be rejected, or the
        newly-appointed user would get president-only access (and the
        outgoing president would lose it) long before the intended date."""
        future = date.today() + timedelta(days=1)
        response = client.post(
            "/certificates/president-terms",
            json={"user_id": regular_user.id, "started_at": str(future)},
            headers=_auth(admin_token),
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_PRESIDENT_TERM"
