import os
from unittest.mock import patch

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
    assert approved.body_text == "와피스 회원가입 신청이 승인되었습니다!"
    assert approved.message_id.endswith("@waffiestudio.com")

    assert rejected.recipients.to[0].email == "member@example.com"
    assert rejected.subject == "와피스 회원가입 신청이 거절되었습니다."
    assert rejected.body_text == "와피스 회원가입 신청이 거절되었습니다."
