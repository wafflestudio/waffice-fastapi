"""Tests for the certificate of activities (활동증명서) API: rendering/preview +
운영진 초안 생성, plus the president / signature API (회장 서명 등록/변경 +
회장 임기 관리) added by an earlier PR in this stack.

Covers `app/routes/certificates.py`, `app/services/certificate.py`, and the
`app/services/certificate_render.py` PDF pipeline end-to-end against a real
testcontainers MySQL 8 database and (when available) a real WeasyPrint
render. Object storage is mocked the way `tests/test_member_detail.py` mocks
it: `monkeypatch.setattr("app.routes.certificates.OCIObjectStorageService", ...)`.
"""

import base64
import threading
import uuid
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
from app.models import Certificate, CertificateSignature, PresidentTerm, User
from app.routes import certificates as certificates_route
from app.services.certificate import (
    CertificateService,
    PresidentService,
    SignatureService,
)

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


def _options(**overrides) -> dict:
    payload = {
        "purpose": "졸업 증빙용",
        "include_qualification_history": False,
        "include_projects": False,
        "include_executive": False,
    }
    payload.update(overrides)
    return payload


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


def _create_draft(client: TestClient, admin_token: str, user_id: int, **opt_overrides):
    """Create a draft certificate.

    Defaults to signer=advisor (the actual DRAFT use case per the spec) so
    tests that only care about the draft's own lifecycle don't also need to
    set up a current president + signature just to get past rendering. Tests
    that specifically exercise signer=president on a draft pass that
    explicitly.
    """
    opts = {"signer": "advisor", "advisor_name": "서진욱"}
    opts.update(opt_overrides)
    return client.post(
        "/certificates/drafts",
        json={"user_id": user_id, "options": _options(**opts)},
        headers=_auth(admin_token),
    )


# ---------------------------------------------------------------------------
# Object storage mock: in-memory dict shared across the requests of a single
# test (so an upload in one call is readable by `get_bytes` in another, e.g.
# signature upload -> preview/draft rendering that embeds it).
#
# This stack uses `OCIObjectStorageService()` directly in the route (not the
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

        def public_url(self, object_name: str) -> str:
            return f"https://fake.local/{object_name}"

    monkeypatch.setattr(
        "app.routes.certificates.OCIObjectStorageService", FakeObjectStorage
    )
    return data


class TestPreview:
    """POST /certificates/preview (member; require_certificate_eligible)."""

    def test_associate_cannot_preview(self, client: TestClient, associate_token: str):
        response = client.post(
            "/certificates/preview", json=_options(), headers=_auth(associate_token)
        )
        assert response.status_code == 403
        assert response.json()["error"] == "ASSOCIATE_CANNOT_ISSUE_CERTIFICATE"

    def test_no_current_president_returns_409(
        self, client: TestClient, regular_token: str
    ):
        """No `president_terms` row at all -> PRESIDENT_NOT_FOUND. Preview is
        not persisted, but it is still fully rendered (with the issue number
        masked to 'XXXX'), so with the default signer=president it fails
        exactly like issuance would when no president is configured."""
        response = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert response.status_code == 409
        assert response.json()["error"] == "PRESIDENT_NOT_FOUND"

    def test_president_without_signature_returns_409(
        self,
        client: TestClient,
        regular_token: str,
        open_president_term: PresidentTerm,
    ):
        """President exists but never registered a signature -> PRESIDENT_SIGNATURE_NOT_FOUND."""
        response = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert response.status_code == 409
        assert response.json()["error"] == "PRESIDENT_SIGNATURE_NOT_FOUND"

    @pytest.mark.usefixtures("open_president_term")
    def test_advisor_signer_rejected_on_preview(
        self, client: TestClient, regular_token: str
    ):
        """signer=advisor is only allowed on the DRAFT path -- a member's own
        preview must go through the president."""
        response = client.post(
            "/certificates/preview",
            json=_options(signer="advisor", advisor_name="서진욱"),
            headers=_auth(regular_token),
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CERTIFICATE_OPTIONS"

    def test_corrupted_signature_returns_502_not_unhandled_500(
        self,
        client: TestClient,
        regular_token: str,
        president_token: str,
        open_president_term: PresidentTerm,
    ):
        """A signature upload can pass the upload-time magic-byte check
        (`_is_png`) while still being a truncated/corrupted image body --
        Pillow only raises when it actually decodes pixel data, which
        `_is_png` never does. `_signature_data_uri` (called from
        `_resolve_signer`, before `render_pdf`) must convert that Pillow
        decode failure into the same `CERTIFICATE_RENDER_FAILED` (502) every
        other rendering failure produces, not let it escape as an unhandled
        500. Does not need `weasyprint` installed: the failure happens while
        resolving the signer, before `render_pdf` is ever reached."""
        truncated_png = VALID_PNG_BYTES[:20]
        assert truncated_png.startswith(PNG_MAGIC)  # still passes _is_png
        upload_resp = _upload_signature(client, president_token, body=truncated_png)
        assert upload_resp.status_code == 200

        preview_resp = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert preview_resp.status_code == 502
        assert preview_resp.json()["error"] == "CERTIFICATE_RENDER_FAILED"

    def test_happy_path_preview_renders_pdf_and_masks_issue_number(
        self,
        client: TestClient,
        db: Session,
        regular_token: str,
        president_token: str,
        open_president_term: PresidentTerm,
    ):
        pytest.importorskip("weasyprint")
        upload_resp = _upload_signature(client, president_token)
        assert upload_resp.status_code == 200

        preview_resp = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert preview_resp.status_code == 200
        assert preview_resp.headers["content-type"] == "application/pdf"
        assert preview_resp.content.startswith(PDF_MAGIC)
        # Not persisted.
        assert db.query(Certificate).count() == 0


class TestDraftCertificates:
    """POST /certificates/drafts + POST /certificates/drafts/preview (admin)."""

    def test_non_admin_cannot_create_draft(
        self, client: TestClient, regular_token: str, regular_user: User
    ):
        response = _create_draft(client, regular_token, regular_user.id)
        assert response.status_code == 403

    def test_draft_for_pending_target_is_rejected(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        pending_user: User,
    ):
        """Admin drafts only checked that the target user *exists*
        (`get_existing_target_user`), never that they meet the same
        REGULAR/ACTIVE eligibility rule `require_certificate_eligible`
        enforces for self-service `/preview` -- so an admin could persist an
        ORIGINAL_PENDING `Certificate` for a PENDING/ASSOCIATE member,
        bypassing the qualification gate. Must be rejected the same way
        self-service is, and nothing may be persisted."""
        response = _create_draft(client, admin_token, pending_user.id)
        assert response.status_code == 403
        assert response.json()["error"] == "ASSOCIATE_CANNOT_ISSUE_CERTIFICATE"
        assert db.query(Certificate).count() == 0

    def test_draft_for_associate_target_is_rejected(
        self, client: TestClient, admin_token: str, associate_user: User
    ):
        response = _create_draft(client, admin_token, associate_user.id)
        assert response.status_code == 403
        assert response.json()["error"] == "ASSOCIATE_CANNOT_ISSUE_CERTIFICATE"

    def test_draft_preview_for_pending_target_is_rejected(
        self, client: TestClient, admin_token: str, pending_user: User
    ):
        response = client.post(
            "/certificates/drafts/preview",
            json={
                "user_id": pending_user.id,
                "options": _options(signer="advisor", advisor_name="서진욱"),
            },
            headers=_auth(admin_token),
        )
        assert response.status_code == 403
        assert response.json()["error"] == "ASSOCIATE_CANNOT_ISSUE_CERTIFICATE"

    def test_draft_creation_is_pending_without_issue_number(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        admin_user: User,
        regular_user: User,
    ):
        pytest.importorskip("weasyprint")
        response = _create_draft(client, admin_token, regular_user.id)
        assert response.status_code == 200
        detail = response.json()["data"]

        assert detail["kind"] == "draft"
        assert detail["status"] == "original_pending"
        assert detail["issue_number"] is None
        assert detail["issued_at"] is None
        assert detail["requested_by"]["id"] == admin_user.id
        assert detail["user"]["id"] == regular_user.id

        assert len(detail["events"]) == 1
        assert detail["events"][0]["action"] == "draft_created"
        assert detail["events"][0]["actor_type"] == "admin"
        assert detail["events"][0]["actor"]["id"] == admin_user.id

        db_cert = db.get(Certificate, detail["id"])
        assert db_cert.pdf_object_key is not None

    def test_draft_allows_advisor_signer_without_a_president(
        self, client: TestClient, admin_token: str, regular_user: User
    ):
        """signer=advisor is the whole point of the DRAFT path -- it must not
        require a current president/signature at all."""
        pytest.importorskip("weasyprint")
        response = _create_draft(
            client,
            admin_token,
            regular_user.id,
            signer="advisor",
            advisor_name="서진욱",
        )
        assert response.status_code == 200
        assert response.json()["data"]["status"] == "original_pending"

    def test_draft_advisor_signer_without_name_is_rejected(
        self, client: TestClient, admin_token: str, regular_user: User
    ):
        response = _create_draft(
            client, admin_token, regular_user.id, signer="advisor", advisor_name=None
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CERTIFICATE_OPTIONS"

    def test_draft_preview_does_not_persist(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
    ):
        pytest.importorskip("weasyprint")
        response = client.post(
            "/certificates/drafts/preview",
            json={
                "user_id": regular_user.id,
                "options": _options(signer="advisor", advisor_name="서진욱"),
            },
            headers=_auth(admin_token),
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(PDF_MAGIC)
        assert db.query(Certificate).count() == 0

    def test_draft_preview_unknown_user_returns_404(
        self, client: TestClient, admin_token: str
    ):
        response = client.post(
            "/certificates/drafts/preview",
            json={
                "user_id": 999_999,
                "options": _options(signer="advisor", advisor_name="서진욱"),
            },
            headers=_auth(admin_token),
        )
        assert response.status_code == 404


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
        """A genuinely non-image content-type (not in the PNG/JPEG/WebP
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
        """PNG (regression), JPEG, and WebP -- each with a real image
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

    def test_upload_rejects_gif(
        self, client: TestClient, president_token: str, open_president_term
    ):
        """GIF is deliberately excluded from the allowlist -- animated frames
        aren't validated, and profile image upload also excludes GIF, so
        signatures stay consistent with that."""
        response = _upload_signature(
            client, president_token, body=VALID_GIF_BYTES, content_type="image/gif"
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_SIGNATURE_FILE"

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


class TestSignatureDataUriMime:
    """`_signature_data_uri` (app/services/certificate.py) re-encodes every stored
    signature into a red-ink, transparent-background PNG (via
    `to_ink_signature_png`) before embedding it in the rendered PDF. Any uploaded
    format (PNG/JPEG/WebP/GIF, opaque or transparent) is therefore normalized to a
    single image/png data URI, so an opaque white background never paints a box
    over the certificate text. Exercised directly through
    `CertificateService._resolve_signer` (the render path), without needing
    WeasyPrint installed."""

    def _resolved_data_uri(self, db: Session) -> str:
        from app.schemas.certificate import CertificateOptions

        options = CertificateOptions(**_options())
        _, data_uri = CertificateService._resolve_signer(
            db, options=options, storage=certificates_route.OCIObjectStorageService()
        )
        assert data_uri is not None
        return data_uri

    def _embedded_png(self, data_uri: str):
        import base64
        from io import BytesIO

        from PIL import Image

        assert data_uri.startswith("data:image/png;base64,")
        raw = base64.b64decode(data_uri.split(",", 1)[1])
        return Image.open(BytesIO(raw))

    def test_jpeg_signature_is_normalized_to_transparent_png(
        self,
        client: TestClient,
        db: Session,
        president_token: str,
        open_president_term: PresidentTerm,
    ):
        upload = _upload_signature(
            client, president_token, body=VALID_JPEG_BYTES, content_type="image/jpeg"
        )
        assert upload.status_code == 200
        # A JPEG signature is re-encoded to PNG (not left as image/jpeg) and gains
        # an alpha channel so its background renders transparent, not as a box.
        img = self._embedded_png(self._resolved_data_uri(db))
        assert img.mode == "RGBA"

    def test_png_signature_embeds_as_image_png(
        self,
        client: TestClient,
        db: Session,
        president_token: str,
        open_president_term: PresidentTerm,
    ):
        upload = _upload_signature(client, president_token)  # default: real PNG
        assert upload.status_code == 200
        assert self._resolved_data_uri(db).startswith("data:image/png;base64,")


class TestRenderContextMasking:
    """`build_context` is a pure function -- exercise the issue-number
    masking contract directly, without needing WeasyPrint installed."""

    def test_issue_number_is_masked_when_none(self, db: Session, regular_user: User):
        from app.services.certificate_render import build_context

        context = build_context(
            db,
            regular_user,
            _options(),
            issue_number=None,
            issued_on=date(2026, 1, 1),
            president_name="회장",
            signature_data_uri=None,
        )
        assert context["issue_number_display"] == "XXXX"
        assert context["verify_url"].endswith("/verify/XXXX")

    def test_issue_number_is_shown_when_present(self, db: Session, regular_user: User):
        from app.services.certificate_render import build_context

        real_number = str(uuid.uuid4())
        context = build_context(
            db,
            regular_user,
            _options(),
            issue_number=real_number,
            issued_on=date(2026, 1, 1),
            president_name="회장",
            signature_data_uri=None,
        )
        assert context["issue_number_display"] == real_number
        assert context["verify_url"].endswith(f"/verify/{real_number}")


class TestPurposeOmittedFromRender:
    """발급 용도(purpose) is an application-input field, not certificate body
    content: `build_context` still carries it (it is stored verbatim in
    `certificates.options`/the snapshot for the 90-day original comparison),
    but the rendered document itself must never print it."""

    def test_purpose_is_not_rendered_in_html(self, db: Session, regular_user: User):
        from app.services.certificate_render import (
            _TEMPLATE_NAME,
            _jinja_env,
            build_context,
        )

        context = build_context(
            db,
            regular_user,
            _options(purpose="취업 지원용"),
            issue_number=None,
            issued_on=date(2026, 1, 1),
            president_name="회장",
            signature_data_uri=None,
        )
        # Still present in the context (-> still saved to the snapshot).
        assert context["purpose"] == "취업 지원용"

        # ... but never printed onto the document body.
        html = _jinja_env.get_template(_TEMPLATE_NAME).render(**context)
        assert "발급 용도" not in html
        assert "취업 지원용" not in html
