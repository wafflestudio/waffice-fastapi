import os
from unittest.mock import patch

from app.config.secrets import get_email_secrets
from app.services.email import SENDER, EmailService


class FakeEmailClient:
    def __init__(self):
        self.submitted = []

    def submit_email(self, details):
        self.submitted.append(details)


def test_signup_notification_messages():
    client = FakeEmailClient()
    EmailService._client = client  # type: ignore[assignment]

    try:
        with patch.dict(
            os.environ,
            {
                "EMAIL_COMPARTMENT_ID": "ocid1.compartment.oc1..test",
                "EMAIL_FROM_EMAIL": SENDER,
                "EMAIL_FROM_NAME": "와피스",
                "EMAIL_REPLY_TO": SENDER,
            },
        ):
            EmailService.send_signup_approved("member@example.com")
            EmailService.send_signup_rejected("member@example.com")
    finally:
        EmailService._client = None

    approved, rejected = client.submitted
    assert approved.sender.compartment_id == "ocid1.compartment.oc1..test"
    assert approved.sender.sender_address.email == SENDER
    assert approved.sender.sender_address.name == "와피스"
    assert approved.recipients.to[0].email == "member@example.com"
    assert approved.reply_to[0].email == SENDER
    assert approved.subject == "와피스 회원가입 신청이 승인되었습니다!"
    assert "회원가입 신청이 승인되었습니다." in approved.body_text
    assert "와피스 드림" in approved.body_text
    assert approved.message_id.endswith("@waffiestudio.com")

    assert rejected.recipients.to[0].email == "member@example.com"
    assert rejected.subject == "와피스 회원가입 신청이 거절되었습니다."
    assert "신청이 승인되지 않았습니다." in rejected.body_text
    assert "와피스 드림" in rejected.body_text


def test_lowercase_kubernetes_email_secrets(monkeypatch):
    for name in (
        "EMAIL_COMPARTMENT_ID",
        "EMAIL_FROM_EMAIL",
        "EMAIL_FROM_NAME",
        "EMAIL_REPLY_TO",
    ):
        monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("email_compartment_id", "ocid1.compartment.oc1..test")
    monkeypatch.setenv("email_from_email", "sender@example.com")
    monkeypatch.setenv("email_from_name", "와피스")
    monkeypatch.setenv("email_reply_to", "reply@example.com")

    assert get_email_secrets() == {
        "compartment_id": "ocid1.compartment.oc1..test",
        "from_email": "sender@example.com",
        "from_name": "와피스",
        "reply_to": "reply@example.com",
    }
