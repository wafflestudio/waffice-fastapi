import logging
import os
from uuid import uuid4

import oci
from oci.email_data_plane import EmailDPClient
from oci.email_data_plane.models import (
    EmailAddress,
    Recipients,
    Sender,
    SubmitEmailDetails,
)
from oci.exceptions import BaseRequestException, InvalidConfig, ServiceError

from app.config.secrets import ENV, get_email_secrets

SENDER = "master@waffiestudio.com"
logger = logging.getLogger(__name__)


class EmailService:
    _client: EmailDPClient | None = None

    @classmethod
    def _send(cls, recipient: str, subject: str, body: str) -> None:
        secrets = get_email_secrets()
        compartment_id = secrets["compartment_id"]
        if not compartment_id:
            if ENV == "local":
                return
            raise RuntimeError("EMAIL_COMPARTMENT_ID is not configured")

        from_email = secrets["from_email"]
        sender_address = EmailAddress(email=from_email)
        from_name = secrets["from_name"]
        reply_to = secrets["reply_to"] or from_email
        if from_name:
            sender_address.name = from_name

        try:
            cls._get_client().submit_email(
                SubmitEmailDetails(
                    message_id=f"{uuid4()}@{from_email.rsplit('@', 1)[-1]}",
                    sender=Sender(
                        sender_address=sender_address,
                        compartment_id=compartment_id,
                    ),
                    recipients=Recipients(to=[EmailAddress(email=recipient)]),
                    subject=subject,
                    body_text=body,
                    reply_to=[EmailAddress(email=reply_to)],
                )
            )
        except (
            BaseRequestException,
            InvalidConfig,
            OSError,
            ServiceError,
            ValueError,
        ) as exc:
            logger.exception(
                "Failed to send signup notification email to %s", recipient
            )
            raise RuntimeError("Failed to send signup notification email") from exc

    @classmethod
    def _get_client(cls) -> EmailDPClient:
        if cls._client is not None:
            return cls._client

        region = os.getenv("OCI_REGION", "ap-chuncheon-1")

        try:
            signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        except Exception as exc:
            if ENV != "local":
                raise RuntimeError("OCI instance principal is not configured") from exc
            config_file = os.getenv("OCI_CONFIG_FILE") or "~/.oci/config"
            profile = os.getenv("OCI_CONFIG_PROFILE", "DEFAULT")
            cls._client = EmailDPClient(oci.config.from_file(config_file, profile))
        else:
            cls._client = EmailDPClient({"region": region}, signer=signer)

        return cls._client

    @classmethod
    def send_signup_approved(cls, recipient: str) -> None:
        cls._send(
            recipient,
            "와피스 회원가입 신청이 승인되었습니다!",
            """안녕하세요, 와플스튜디오 회원관리 포털 와피스입니다.

회원가입 신청이 승인되었습니다.
이제 와피스에 로그인하여 서비스를 이용하실 수 있습니다.

감사합니다.
와피스 드림""",
        )

    @classmethod
    def send_signup_rejected(cls, recipient: str) -> None:
        cls._send(
            recipient,
            "와피스 회원가입 신청이 거절되었습니다.",
            """안녕하세요, 와피스입니다.

회원가입 신청 검토 결과, 신청이 승인되지 않았습니다.

감사합니다.
와피스 드림""",
        )
