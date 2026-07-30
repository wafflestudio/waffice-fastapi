"""Tests for the certificate of activities (활동증명서) API: rendering/preview +
운영진 초안 생성, plus the president signature API (회장 서명 등록/변경) added by
an earlier PR in this stack. 회장(is_president) 임명은 이제 운영팀 프로젝트
멤버십으로 관리되며 (app/routes/projects.py), 이 파일 범위 밖이다.

Covers `app/routes/certificates.py`, `app/services/certificate.py`, and one
end-to-end `app/services/certificate_render.py` smoke test against a real
testcontainers MySQL 8 database and (when available) WeasyPrint. Other tests
stub PDF rendering and mock object storage.
"""

import base64
import threading
import time
import uuid
from datetime import date, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session, sessionmaker

from app.exceptions import CertificateAlreadyIssuedError, SignatureUploadConflictError
from app.models import (
    Certificate,
    CertificateEvent,
    CertificateSignature,
    Project,
    ProjectMember,
    User,
    UserActivity,
)
from app.models.enums import (
    ActivityStatus,
    AuditAction,
    CertificateKind,
    CertificateStatus,
    MemberRole,
)
from app.routes import certificates as certificates_route
from app.services.certificate import (
    CertificateService,
    SignatureService,
    render_pdf as _real_render_pdf,
)

pytestmark = pytest.mark.usefixtures("fake_storage")

# A real (tiny, 1x1 transparent) PNG.
VALID_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF-"
VALID_PDF_BYTES = PDF_MAGIC + b"1.4 fake offline-signed certificate original"


@pytest.fixture(autouse=True)
def stub_pdf_render(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.certificate.render_pdf", lambda _: VALID_PDF_BYTES
    )


@pytest.fixture
def real_pdf_render(monkeypatch: pytest.MonkeyPatch):
    try:
        __import__("weasyprint")
    except (ImportError, OSError) as exc:
        pytest.skip(f"WeasyPrint unavailable: {exc}")
    monkeypatch.setattr("app.services.certificate.render_pdf", _real_render_pdf)


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
        not persisted, but it is still fully rendered, so with the default
        signer=president it fails exactly like issuance would when no president
        is configured."""
        response = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert response.status_code == 409
        assert response.json()["error"] == "PRESIDENT_NOT_FOUND"

    def test_president_without_signature_returns_409(
        self,
        client: TestClient,
        regular_token: str,
        open_president_term: User,
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
        open_president_term: User,
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

    def test_happy_path_preview_renders_pdf(
        self,
        client: TestClient,
        db: Session,
        regular_token: str,
        president_token: str,
        open_president_term: User,
        real_pdf_render,
    ):
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


class TestSelfIssuance:
    """POST /certificates (kind=SELF)."""

    def test_associate_cannot_issue(self, client: TestClient, associate_token: str):
        response = client.post(
            "/certificates", json=_options(), headers=_auth(associate_token)
        )
        assert response.status_code == 403
        assert response.json()["error"] == "ASSOCIATE_CANNOT_ISSUE_CERTIFICATE"

    def test_no_current_president_returns_409(
        self, client: TestClient, regular_token: str
    ):
        """No `president_terms` row at all -> PRESIDENT_NOT_FOUND."""
        response = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        )
        assert response.status_code == 409
        assert response.json()["error"] == "PRESIDENT_NOT_FOUND"

    def test_president_without_signature_returns_409(
        self,
        client: TestClient,
        regular_token: str,
        open_president_term: User,
    ):
        """President exists but never registered a signature -> PRESIDENT_SIGNATURE_NOT_FOUND."""
        response = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        )
        assert response.status_code == 409
        assert response.json()["error"] == "PRESIDENT_SIGNATURE_NOT_FOUND"

    @pytest.mark.usefixtures("open_president_term")
    def test_advisor_signer_rejected_on_self_issue(
        self, client: TestClient, regular_token: str
    ):
        response = client.post(
            "/certificates",
            json=_options(signer="advisor", advisor_name="서진욱"),
            headers=_auth(regular_token),
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CERTIFICATE_OPTIONS"

    def test_happy_path_self_issue(
        self,
        client: TestClient,
        db: Session,
        regular_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        upload_resp = _upload_signature(client, president_token)
        assert upload_resp.status_code == 200

        # Preview first: generated but not persisted.
        preview_resp = client.post(
            "/certificates/preview", json=_options(), headers=_auth(regular_token)
        )
        assert preview_resp.status_code == 200
        assert preview_resp.headers["content-type"] == "application/pdf"
        assert preview_resp.content.startswith(PDF_MAGIC)
        assert db.query(Certificate).count() == 0

        issue_resp = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        )
        assert issue_resp.status_code == 200
        body = issue_resp.json()
        assert body["ok"] is True
        detail = body["data"]

        assert detail["status"] == "issued"
        assert detail["kind"] == "self"
        assert detail["user"]["id"] == regular_user.id
        assert detail["requested_by"]["id"] == regular_user.id
        assert detail["issued_at"] is not None
        assert detail["expires_at"] == detail["issued_at"] + 90 * 24 * 3600

        # issue_number is a real UUID (raises if malformed).
        uuid.UUID(detail["issue_number"])

        actions = [(e["action"], e["actor_type"]) for e in detail["events"]]
        assert actions == [
            ("applied", "applicant"),
            ("issued", "system"),
        ]
        assert detail["events"][0]["actor"]["id"] == regular_user.id
        assert detail["events"][1]["actor"] is None

        cert_id = detail["id"]
        events_in_db = (
            db.query(CertificateEvent)
            .filter(CertificateEvent.certificate_id == cert_id)
            .count()
        )
        assert events_in_db == 2

        # PDF actually got uploaded to (fake) object storage.
        db_cert = db.get(Certificate, cert_id)
        assert db_cert.pdf_object_key is not None

        download_resp = client.get(
            f"/certificates/{cert_id}/download", headers=_auth(regular_token)
        )
        assert download_resp.status_code == 200
        assert download_resp.headers["content-type"] == "application/pdf"
        assert download_resp.content.startswith(PDF_MAGIC)

    def test_discipline_section_always_renders(
        self,
        client: TestClient,
        db: Session,
        regular_token: str,
        president_token: str,
        open_president_term: User,
    ):
        """Section 3 (징계) is always present in the snapshot even when every
        optional section is off -- it cannot be deselected."""
        assert _upload_signature(client, president_token).status_code == 200

        issue_resp = client.post(
            "/certificates",
            json=_options(
                include_qualification_history=False,
                include_projects=False,
                include_executive=False,
            ),
            headers=_auth(regular_token),
        )
        assert issue_resp.status_code == 200
        cert_id = issue_resp.json()["data"]["id"]

        db_cert = db.get(Certificate, cert_id)
        section_types = [s["type"] for s in db_cert.snapshot["sections"]]
        assert "discipline" in section_types
        discipline = next(
            s for s in db_cert.snapshot["sections"] if s["type"] == "discipline"
        )
        assert discipline["title"] == "징계 의결의 주문, 이유, 의결일 및 징계 개시일"
        assert discipline["rows"] == []
        # Only the always-on sections (기본 인적 사항, 징계) are present.
        assert section_types == ["personal", "discipline"]

    def test_qualification_history_section_includes_reasons_with_legacy_fallback(
        self,
        client: TestClient,
        db: Session,
        regular_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        assert _upload_signature(client, president_token).status_code == 200

        from app.models import AuditLog

        log = AuditLog(
            user_id=regular_user.id,
            actor_id=None,
            action=AuditAction.QUALIFICATION_CHANGED,
            payload={
                "from": "associate",
                "to": "regular",
                "reason": "정회원 승급 요건 충족",
            },
        )
        legacy_log = AuditLog(
            user_id=regular_user.id,
            actor_id=None,
            action=AuditAction.QUALIFICATION_CHANGED,
            payload={"from": "regular", "to": "active"},
        )
        db.add_all([log, legacy_log])
        db.commit()

        issue_resp = client.post(
            "/certificates",
            json=_options(include_qualification_history=True),
            headers=_auth(regular_token),
        )
        assert issue_resp.status_code == 200
        cert_id = issue_resp.json()["data"]["id"]

        db_cert = db.get(Certificate, cert_id)
        qualification_section = next(
            s for s in db_cert.snapshot["sections"] if s["type"] == "qualification"
        )
        rows = qualification_section["rows"]
        assert rows[0]["content"] == "회원 자격 취득"
        assert rows[0]["reason"] == "-"
        assert rows[1]["content"] == "준회원 → 정회원"
        assert rows[1]["reason"] == "정회원 승급 요건 충족"
        assert rows[2]["content"] == "정회원 → 활동회원"
        assert rows[2]["reason"] == "-"


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


class TestOriginalRegistration:
    """POST /certificates/{id}/original (president only)."""

    def test_non_president_admin_forbidden(
        self, client: TestClient, admin_token: str, regular_user: User
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(admin_token),
        )
        assert response.status_code == 403

    def test_president_registers_original(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        president_token: str,
        president_user: User,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        assert draft["status"] == "original_pending"

        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(president_token),
        )
        assert response.status_code == 200
        detail = response.json()["data"]
        assert detail["status"] == "issued"
        assert detail["issued_at"] is not None
        uuid.UUID(detail["issue_number"])

        actions = [e["action"] for e in detail["events"]]
        assert actions == ["draft_created", "original_registered"]
        assert detail["events"][-1]["actor_type"] == "president"
        assert detail["events"][-1]["actor"]["id"] == president_user.id

        # The uploaded bytes are stored verbatim (system does not re-render).
        stored = client.get(
            f"/certificates/{draft['id']}/download", headers=_auth(admin_token)
        )
        assert stored.content == VALID_PDF_BYTES

    def test_register_original_snapshot_reflects_registration_time_data_not_draft_time(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        """Characterization test for a known limitation flagged in
        `CertificateService.register_original`'s docstring (DIVERGENCE --
        needs product/eng sign-off, not silently fixed here).

        `register_original` rebuilds `certificate.snapshot` from *current*
        DB state at registration time, not from the render context
        `create_draft` actually produced for the physically-printed/signed
        document (which is never persisted). If the member's data changes
        during the offline-signing gap -- the entire reason this two-step
        flow exists -- the "frozen at issuance" snapshot silently ends up
        describing content different from what's on the signed original.

        This pins the *current* drifting behavior so a future intentional
        fix (e.g. persisting the draft-time context so registration can
        reuse it) has to consciously update this test rather than
        regressing unnoticed.
        """
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]

        # Simulate the offline-signing gap: the member's data changes after
        # the draft (and its physical printout) already exists.
        regular_user.name = "개명후이름"
        db.add(regular_user)
        db.commit()

        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(president_token),
        )
        assert response.status_code == 200

        stored = CertificateService.get(db, draft["id"])
        personal_section = next(
            section
            for section in stored.snapshot["sections"]
            if section["type"] == "personal"
        )
        # Current (documented-limitation) behavior: the snapshot reflects
        # the post-drift name, not what was on the printed/signed original.
        assert personal_section["data"]["name"] == "개명후이름"

    def test_reregistering_an_issued_certificate_conflicts(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        first = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(president_token),
        )
        assert first.status_code == 200

        second = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(president_token),
        )
        assert second.status_code == 409
        assert second.json()["error"] == "CERTIFICATE_ALREADY_ISSUED"

    def test_register_original_race_is_not_lost_to_toctou(
        self,
        client: TestClient,
        engine,
        admin_token: str,
        regular_user: User,
        president_user: User,
        open_president_term: User,
        fake_storage: dict,
    ):
        """Two near-simultaneous `/original` requests for the same
        ORIGINAL_PENDING certificate (e.g. a double-click during a slow
        upload) must not both succeed. Without a row lock + status recheck
        against the freshest committed state, both requests can load the
        same ORIGINAL_PENDING row, both pass the guard, and both commit --
        the second silently overwriting the first's issue_number and
        pdf_object_key. This drives two independent DB sessions (real
        concurrent transactions, not just two HTTP calls sharing the single
        `client` session) through `CertificateService.register_original`
        directly, synchronized with a barrier to maximize overlap.
        """
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        cert_id = draft["id"]

        session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        barrier = threading.Barrier(2)
        results: list[tuple[str, str | None, str | None]] = []
        results_lock = threading.Lock()

        def worker(body: bytes) -> None:
            session = session_factory()
            try:
                barrier.wait()
                certificate = CertificateService.get(session, cert_id)
                try:
                    updated = CertificateService.register_original(
                        session,
                        president=president_user,
                        certificate=certificate,
                        file_bytes=body,
                        storage=certificates_route.OCIObjectStorageService(),
                    )
                    outcome = ("ok", updated.issue_number, updated.pdf_object_key)
                except CertificateAlreadyIssuedError:
                    outcome = ("conflict", None, None)
                with results_lock:
                    results.append(outcome)
            finally:
                session.close()

        body_a = PDF_MAGIC + b"1.4 request A original"
        body_b = PDF_MAGIC + b"1.4 request B original"
        t1 = threading.Thread(target=worker, args=(body_a,))
        t2 = threading.Thread(target=worker, args=(body_b,))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert len(results) == 2
        oks = [r for r in results if r[0] == "ok"]
        conflicts = [r for r in results if r[0] == "conflict"]
        assert len(oks) == 1, (
            "both concurrent /original requests reported success -- the "
            "second silently overwrote the first winner's issue_number/"
            f"pdf_object_key (results={results!r})"
        )
        assert len(conflicts) == 1

        verify_session = session_factory()
        try:
            final = CertificateService.get(verify_session, cert_id)
            assert final.status == CertificateStatus.ISSUED
            winner = oks[0]
            assert final.issue_number == winner[1]
            assert final.pdf_object_key == winner[2]
        finally:
            verify_session.close()

    def test_original_upload_rejects_non_pdf_content_type(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "text/plain")},
            headers=_auth(president_token),
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CERTIFICATE_FILE"

    def test_original_upload_rejects_wrong_magic_bytes(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", b"not-really-a-pdf", "application/pdf")},
            headers=_auth(president_token),
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CERTIFICATE_FILE"

    def test_original_upload_too_large(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        oversized = PDF_MAGIC + b"0" * (10 * 1024 * 1024 + 1)
        response = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", oversized, "application/pdf")},
            headers=_auth(president_token),
        )
        assert response.status_code == 413
        assert response.json()["error"] == "CERTIFICATE_FILE_TOO_LARGE"


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
        open_president_term: User,
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
        open_president_term: User,
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
        open_president_term: User,
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
        open_president_term: User,
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
        open_president_term: User,
    ):
        upload = _upload_signature(client, president_token)  # default: real PNG
        assert upload.status_code == 200
        assert self._resolved_data_uri(db).startswith("data:image/png;base64,")


class TestDownload:
    """GET /certificates/{certificate_id}/download (owner or admin)."""

    def test_owner_can_download(
        self,
        client: TestClient,
        regular_token: str,
        president_token: str,
        open_president_term: User,
    ):
        assert _upload_signature(client, president_token).status_code == 200
        cert = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]

        response = client.get(
            f"/certificates/{cert['id']}/download", headers=_auth(regular_token)
        )
        assert response.status_code == 200
        assert response.content.startswith(PDF_MAGIC)

    def test_other_member_forbidden(
        self,
        client: TestClient,
        regular_token: str,
        active_token: str,
        president_token: str,
        open_president_term: User,
    ):
        assert _upload_signature(client, president_token).status_code == 200
        cert = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]

        response = client.get(
            f"/certificates/{cert['id']}/download", headers=_auth(active_token)
        )
        assert response.status_code == 403

    def test_admin_can_download_anyones_certificate(
        self,
        client: TestClient,
        regular_token: str,
        admin_token: str,
        president_token: str,
        open_president_term: User,
    ):
        assert _upload_signature(client, president_token).status_code == 200
        cert = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]

        response = client.get(
            f"/certificates/{cert['id']}/download", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        assert response.content.startswith(PDF_MAGIC)

    def test_download_without_pdf_returns_404(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
    ):
        """Edge case that shouldn't occur through the normal flow (both SELF
        and DRAFT creation render+upload immediately) but is still a defined
        contract: a certificate row with no pdf_object_key -> 404."""
        cert = Certificate(
            user_id=regular_user.id,
            requested_by_id=regular_user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=_options(),
        )
        db.add(cert)
        db.commit()

        response = client.get(
            f"/certificates/{cert.id}/download", headers=_auth(admin_token)
        )
        assert response.status_code == 404
        assert response.json()["error"] == "CERTIFICATE_NOT_FOUND"

    def test_download_missing_certificate_returns_404(
        self, client: TestClient, admin_token: str
    ):
        response = client.get(
            "/certificates/999999/download", headers=_auth(admin_token)
        )
        assert response.status_code == 404
        assert response.json()["error"] == "CERTIFICATE_NOT_FOUND"


class TestCertificateExpiry:
    """`expires_at` 경과 시 원본 폐기 + CERTIFICATE_EXPIRED (lazy purge on
    access) 및 `POST /certificates/purge-expired` (운영진 일괄 폐기)."""

    def test_download_after_expiry_purges_and_returns_410(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        fake_storage: dict,
    ):
        object_key = f"certificates/expired/{uuid.uuid4()}.pdf"
        fake_storage[object_key] = PDF_MAGIC + b"expired body"
        cert = Certificate(
            user_id=regular_user.id,
            requested_by_id=regular_user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=_options(),
            issue_number=str(uuid.uuid4()),
            pdf_object_key=object_key,
            snapshot={"some": "content"},
            issued_at=int(time.time()),
            expires_at=int(time.time()) - 1,
        )
        db.add(cert)
        db.commit()

        response = client.get(
            f"/certificates/{cert.id}/download", headers=_auth(admin_token)
        )
        assert response.status_code == 410
        assert response.json()["error"] == "CERTIFICATE_EXPIRED"

        db.expire_all()
        row = db.get(Certificate, cert.id)
        assert row.pdf_object_key is None
        assert row.snapshot is None
        assert object_key not in fake_storage

    def test_second_access_after_expiry_still_returns_410(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_user: User,
        fake_storage: dict,
    ):
        """Content is already purged on the first access -- a second access
        must not error out trying to re-purge (`pdf_object_key` is already
        None), and must still report the certificate as expired rather than
        falling through to CERTIFICATE_NOT_FOUND."""
        cert = Certificate(
            user_id=regular_user.id,
            requested_by_id=regular_user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=_options(),
            issue_number=str(uuid.uuid4()),
            pdf_object_key=None,
            snapshot=None,
            issued_at=int(time.time()),
            expires_at=int(time.time()) - 1,
        )
        db.add(cert)
        db.commit()

        response = client.get(
            f"/certificates/{cert.id}/download", headers=_auth(admin_token)
        )
        assert response.status_code == 410
        assert response.json()["error"] == "CERTIFICATE_EXPIRED"

    def test_purge_all_expired_purges_only_expired_rows(
        self,
        db: Session,
        regular_user: User,
        active_user: User,
        fake_storage: dict,
    ):
        """`CertificateService.purge_all_expired` is what the scheduled job
        (`app/scheduler.py`) calls -- exercised directly here rather than
        through an HTTP endpoint, since there is no admin-facing route for
        it (purging is scheduler-only, not operator-triggered)."""
        expired_key = f"certificates/expired/{uuid.uuid4()}.pdf"
        valid_key = f"certificates/valid/{uuid.uuid4()}.pdf"
        fake_storage[expired_key] = PDF_MAGIC + b"expired"
        fake_storage[valid_key] = PDF_MAGIC + b"valid"

        expired_cert = Certificate(
            user_id=regular_user.id,
            requested_by_id=regular_user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=_options(),
            issue_number=str(uuid.uuid4()),
            pdf_object_key=expired_key,
            snapshot={"some": "content"},
            issued_at=int(time.time()),
            expires_at=int(time.time()) - 1,
        )
        valid_cert = Certificate(
            user_id=active_user.id,
            requested_by_id=active_user.id,
            kind=CertificateKind.SELF,
            status=CertificateStatus.ISSUED,
            options=_options(),
            issue_number=str(uuid.uuid4()),
            pdf_object_key=valid_key,
            snapshot={"some": "content"},
            issued_at=int(time.time()),
            expires_at=int(time.time()) + 999999,
        )
        db.add_all([expired_cert, valid_cert])
        db.commit()

        storage = certificates_route.OCIObjectStorageService()
        purged_count = CertificateService.purge_all_expired(db, storage)
        assert purged_count == 1

        db.expire_all()
        assert db.get(Certificate, expired_cert.id).pdf_object_key is None
        assert db.get(Certificate, valid_cert.id).pdf_object_key == valid_key
        assert expired_key not in fake_storage
        assert valid_key in fake_storage


class TestMyCertificates:
    """GET /certificates/me — created_at DESC, id DESC, cursor round-trip."""

    def test_list_own_orders_newest_first_and_paginates(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_token: str,
        regular_user: User,
    ):
        ids = []
        for _ in range(3):
            draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
            ids.append(draft["id"])

        # Own list only shows certs where user_id == self (not requested_by).
        page1 = client.get(
            "/certificates/me?limit=2", headers=_auth(regular_token)
        ).json()["data"]
        assert len(page1["items"]) == 2
        assert page1["next_cursor"] is not None
        assert [item["id"] for item in page1["items"]] == list(reversed(ids))[:2]

        page2 = client.get(
            f"/certificates/me?limit=2&cursor={page1['next_cursor']}",
            headers=_auth(regular_token),
        ).json()["data"]
        assert [item["id"] for item in page2["items"]] == list(reversed(ids))[2:]
        assert page2["next_cursor"] is None

    def test_next_cursor_is_a_json_string_beyond_js_safe_integer(
        self,
        client: TestClient,
        admin_token: str,
        regular_token: str,
        regular_user: User,
    ):
        """`next_cursor` encodes `created_at * _ME_CURSOR_ID_OFFSET + id`, which is
        comfortably larger than JS's safe integer bound
        (`Number.MAX_SAFE_INTEGER` = 2**53 - 1 = 9007199254740991). If this
        were serialized as a plain JSON number, a standard JS/TS client would
        silently round it on `JSON.parse`, corrupting the cursor and causing
        the next page request to skip or duplicate rows. It must round-trip
        as an opaque numeric *string* instead."""
        for _ in range(2):
            _create_draft(client, admin_token, regular_user.id)

        page1 = client.get(
            "/certificates/me?limit=1", headers=_auth(regular_token)
        ).json()["data"]
        cursor = page1["next_cursor"]
        assert isinstance(cursor, str)
        assert int(cursor) > 2**53 - 1

        page2 = client.get(
            f"/certificates/me?limit=1&cursor={cursor}",
            headers=_auth(regular_token),
        )
        assert page2.status_code == 200
        assert len(page2.json()["data"]["items"]) == 1

    def test_invalid_cursor_returns_400(self, client: TestClient, regular_token: str):
        response = client.get(
            "/certificates/me?cursor=not-a-number", headers=_auth(regular_token)
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CURSOR"

    def test_cursor_roundtrips_ids_up_to_int32_max(self):
        """`Certificate.id` is a MySQL `INT` (signed 32-bit) column, so a
        legitimate id can reach 2**31 - 1 (2,147,483,647). `_encode_cursor`/
        `_decode_cursor` multiplex `(created_at, id)` into a single integer
        via `id + created_at * _ME_CURSOR_ID_OFFSET`; if `_ME_CURSOR_ID_OFFSET`
        were <= a real id, `divmod` would decode the wrong (created_at, id)
        pair. Exercise the encode/decode helpers directly (no DB round-trip
        needed) at the column's own ceiling."""
        from app.services.certificate import (
            _ME_CURSOR_ID_OFFSET,
            _decode_cursor,
            _encode_cursor,
        )

        created_at = 1_700_000_000
        cert_id = 2**31 - 1  # INT column max.
        cursor = _encode_cursor(created_at, cert_id, _ME_CURSOR_ID_OFFSET)
        assert _decode_cursor(cursor, _ME_CURSOR_ID_OFFSET) == (created_at, cert_id)

    def test_list_own_excludes_other_users_certificates(
        self,
        client: TestClient,
        admin_token: str,
        regular_token: str,
        regular_user: User,
        active_user: User,
    ):
        _create_draft(client, admin_token, regular_user.id)
        _create_draft(client, admin_token, active_user.id)

        page = client.get("/certificates/me", headers=_auth(regular_token)).json()[
            "data"
        ]
        assert len(page["items"]) == 1
        assert page["items"][0]["id"] is not None


class TestHistoryListing:
    """GET /certificates (admin) — ORIGINAL_PENDING first, then created_at DESC."""

    def test_pending_rows_come_before_issued_rows(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_token: str,
        regular_user: User,
        active_user: User,
        president_token: str,
        open_president_term: User,
    ):
        assert _upload_signature(client, president_token).status_code == 200

        issued = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]
        pending = _create_draft(client, admin_token, active_user.id).json()["data"]

        response = client.get("/certificates?limit=10", headers=_auth(admin_token))
        assert response.status_code == 200
        items = response.json()["data"]["items"]
        statuses = [item["status"] for item in items]
        ids = [item["id"] for item in items]

        assert statuses[0] == "original_pending"
        assert pending["id"] in ids[: statuses.count("original_pending")]
        assert issued["id"] in ids[statuses.count("original_pending") :]
        # All pending rows appear before all issued rows.
        assert statuses == sorted(statuses, key=lambda s: s != "original_pending")

    def test_priority_sort_beats_created_at_when_pending_is_older(
        self,
        client: TestClient,
        db: Session,
        admin_token: str,
        regular_token: str,
        regular_user: User,
        active_user: User,
        president_token: str,
        open_president_term: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """`test_pending_rows_come_before_issued_rows` above creates the
        ISSUED row *first* and the pending draft *second*, so the pending
        row also happens to be the newer row -- a plain `created_at DESC`
        with no `pending_priority` at all would already sort it first, so
        that test cannot actually tell `ORDER BY pending_priority DESC,
        created_at DESC, id DESC` apart from a buggy `ORDER BY created_at
        DESC, id DESC`. This test makes the ORIGINAL_PENDING draft strictly
        *older* than the ISSUED certificate, so it can only sort first
        because of `pending_priority` -- it must go RED if that column is
        ever dropped from the ORDER BY."""
        assert _upload_signature(client, president_token).status_code == 200

        older = time.time()
        monkeypatch.setattr(time, "time", lambda: older)
        pending = _create_draft(client, admin_token, active_user.id).json()["data"]

        # Comfortably newer than `older`, well beyond the 1-second
        # resolution of `int(time.time())` so the ordering is unambiguous.
        newer = older + 100_000
        monkeypatch.setattr(time, "time", lambda: newer)
        issued = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]

        db_pending = db.get(Certificate, pending["id"])
        db_issued = db.get(Certificate, issued["id"])
        assert db_pending.created_at < db_issued.created_at

        response = client.get("/certificates?limit=10", headers=_auth(admin_token))
        assert response.status_code == 200
        ids = [item["id"] for item in response.json()["data"]["items"]]
        assert ids.index(pending["id"]) < ids.index(issued["id"]), (
            "the older ORIGINAL_PENDING row must still sort before the "
            "newer ISSUED row -- pending_priority must win over created_at"
        )

    def test_next_cursor_is_a_json_string_beyond_int64(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
    ):
        """The history cursor encodes (priority, created_at, id) as
        `(priority * 10**13 + created_at) * 10**10 + id`, which not only
        exceeds JS's safe integer bound but also signed int64
        (2**63 - 1 = 9223372036854775807). If this were serialized as a
        plain JSON number, a JS client could even re-serialize it in
        exponent notation, which the `cursor: int` query param would reject
        with 422. It must round-trip as an opaque numeric *string*."""
        for _ in range(2):
            _create_draft(client, admin_token, regular_user.id)

        page1 = client.get("/certificates?limit=1", headers=_auth(admin_token)).json()[
            "data"
        ]
        cursor = page1["next_cursor"]
        assert isinstance(cursor, str)
        assert int(cursor) > 2**63 - 1

        page2 = client.get(
            f"/certificates?limit=1&cursor={cursor}", headers=_auth(admin_token)
        )
        assert page2.status_code == 200
        assert len(page2.json()["data"]["items"]) == 1

    def test_invalid_cursor_returns_400(self, client: TestClient, admin_token: str):
        response = client.get(
            "/certificates?cursor=not-a-number", headers=_auth(admin_token)
        )
        assert response.status_code == 400
        assert response.json()["error"] == "INVALID_CURSOR"
        assert response.json()["message"] == "잘못된 페이지네이션 커서입니다."

    def test_list_history_requires_admin(self, client: TestClient, regular_token: str):
        response = client.get("/certificates", headers=_auth(regular_token))
        assert response.status_code == 403

    def test_history_detail_requires_admin(
        self,
        client: TestClient,
        admin_token: str,
        regular_token: str,
        regular_user: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]

        response = client.get(
            f"/certificates/{draft['id']}", headers=_auth(regular_token)
        )
        assert response.status_code == 403

    def test_history_detail_returns_full_event_history(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        president_token: str,
        open_president_term: User,
    ):
        draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
        original = client.post(
            f"/certificates/{draft['id']}/original",
            files={"file": ("original.pdf", VALID_PDF_BYTES, "application/pdf")},
            headers=_auth(president_token),
        )
        assert original.status_code == 200

        response = client.get(
            f"/certificates/{draft['id']}", headers=_auth(admin_token)
        )
        assert response.status_code == 200
        detail = response.json()["data"]
        assert detail["status"] == "issued"
        actions = [event["action"] for event in detail["events"]]
        assert actions == ["draft_created", "original_registered"]

    def test_cursor_pagination_round_trips_over_mixed_statuses(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        regular_token: str,
        active_user: User,
        president_token: str,
        open_president_term: User,
    ):
        """Exercises *both* partitions of the (priority, created_at, id)
        keyset -- ORIGINAL_PENDING drafts (priority=1) and an ISSUED
        certificate (priority=0) -- so pagination has to cross the
        priority=1 -> priority=0 boundary at least once. The previous
        version of this test only ever created drafts (all
        ORIGINAL_PENDING), so the cross-partition cursor branch
        (`priority < cursor_priority`) was never exercised."""
        assert _upload_signature(client, president_token).status_code == 200

        created_ids = set()
        for _ in range(5):
            draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
            created_ids.add(draft["id"])

        issued = client.post(
            "/certificates", json=_options(), headers=_auth(regular_token)
        ).json()["data"]
        created_ids.add(issued["id"])

        seen_ids = []
        cursor = None
        for _ in range(10):  # generous upper bound on pages
            url = "/certificates?limit=2"
            if cursor is not None:
                url += f"&cursor={cursor}"
            page = client.get(url, headers=_auth(admin_token)).json()["data"]
            seen_ids.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert cursor is None
        assert set(seen_ids) == created_ids
        assert len(seen_ids) == len(set(seen_ids))  # no duplicates

    def test_cursor_pagination_does_not_drop_rows_created_in_the_same_second(
        self,
        client: TestClient,
        admin_token: str,
        regular_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """`Certificate.created_at` has 1-second resolution
        (`int(time.time())`), so multiple certificates created within the
        same wall-clock second tie on the (priority, created_at) keyset. A
        cursor predicate that only compares `created_at` (with no id
        tiebreak) can silently drop or duplicate tied rows once the page
        boundary lands inside the tie. This freezes time to force the tie
        deterministically."""
        frozen = time.time()
        monkeypatch.setattr(time, "time", lambda: frozen)

        created_ids = set()
        for _ in range(3):
            draft = _create_draft(client, admin_token, regular_user.id).json()["data"]
            created_ids.add(draft["id"])

        seen_ids = []
        cursor = None
        for _ in range(10):
            url = "/certificates?limit=1"
            if cursor is not None:
                url += f"&cursor={cursor}"
            page = client.get(url, headers=_auth(admin_token)).json()["data"]
            seen_ids.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break

        assert set(seen_ids) == created_ids
        assert len(seen_ids) == len(created_ids), (
            "cursor pagination lost or duplicated rows that tied on "
            "(priority, created_at) within the same second"
        )


class TestRenderContextMasking:
    """Keep issue metadata available internally for future verification."""

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


class TestProjectRows:
    def test_uses_activity_history_instead_of_project_memberships(
        self, db: Session, regular_user: User
    ):
        from app.services.certificate_render import build_context

        activity_project = Project(name="승인된 활동", started_at=date(2025, 1, 1))
        membership_only_project = Project(name="멤버십만 존재", started_at=date(2025, 1, 1))
        db.add_all([activity_project, membership_only_project])
        db.flush()
        db.add_all(
            [
                ProjectMember(
                    project_id=membership_only_project.id,
                    user_id=regular_user.id,
                    role=MemberRole.MEMBER,
                    position="출력되면 안 됨",
                    joined_at=date(2025, 1, 1),
                ),
                UserActivity(
                    user_id=regular_user.id,
                    project_id=activity_project.id,
                    position="백엔드",
                    start_date=1735689600,
                    end_date=1743465600,
                    status=ActivityStatus.INACTIVE,
                ),
            ]
        )
        db.commit()

        context = build_context(
            db,
            regular_user,
            _options(include_projects=True),
            issue_number=None,
            issued_on=date(2026, 1, 1),
            president_name="회장",
            signature_data_uri=None,
        )
        project_section = next(
            section for section in context["sections"] if section["type"] == "projects"
        )

        assert project_section["rows"] == [
            {
                "name": "승인된 활동",
                "period": "2025.01.01. ~ 2025.04.01.",
                "role": "백엔드",
            }
        ]


class TestIssueAndVerificationOmittedFromRender:
    """Issue metadata stays internal until certificate verification exists."""

    @pytest.mark.parametrize("issue_number", [None, str(uuid.uuid4())])
    def test_issue_metadata_is_not_rendered_in_html(
        self,
        db: Session,
        regular_user: User,
        issue_number: str | None,
    ):
        from app.services.certificate_render import (
            _TEMPLATE_NAME,
            _jinja_env,
            build_context,
        )

        context = build_context(
            db,
            regular_user,
            _options(),
            issue_number=issue_number,
            issued_on=date(2026, 1, 1),
            president_name="회장",
            signature_data_uri=None,
        )
        html = _jinja_env.get_template(_TEMPLATE_NAME).render(**context)

        assert "발행번호" not in html
        assert "증명서 원본 확인 사이트" not in html
        assert context["issue_number_display"] not in html
        assert context["verify_url"] not in html


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
