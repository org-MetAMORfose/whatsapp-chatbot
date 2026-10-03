"""Gmail SMTP adapter for transactional e-mail."""

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from hashlib import sha256
from typing import ClassVar

from app.config import settings
from app.domain.whatsapp.matching_patient_template import whatsapp_phone


@dataclass(frozen=True)
class MatchingProfessionalEmail:
    recipient: str
    patient_name: str
    patient_area: str
    patient_phone: str

    subject: ClassVar[str] = "Novo paciente pela MetAMORfose"

    def __post_init__(self) -> None:
        if not isinstance(self.recipient, str):
            raise ValueError("Missing professional email")
        recipient = self.recipient.strip()
        _, parsed = parseaddr(recipient)
        if parsed != recipient or "@" not in recipient:
            raise ValueError("Missing or invalid professional email")
        object.__setattr__(self, "recipient", recipient)
        object.__setattr__(self, "patient_phone", whatsapp_phone(self.patient_phone))
        for field in ("patient_name", "patient_area"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Missing {field}")
            object.__setattr__(self, field, value.strip())

    @property
    def body(self) -> str:
        return (
            "Você recebeu um novo paciente pela MetAMORfose.\n"
            f"👤 Paciente: {self.patient_name}\n"
            f"📋 Área: {self.patient_area}\n"
            "Contato do paciente:\n"
            f"https://wa.me/{self.patient_phone}\n"
            "Este envio é referente ao seu ciclo de atendimento ativo."
        )


class GmailSmtpAdapter:
    host = "smtp.gmail.com"
    port = 465
    timeout = 30

    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self.username = settings.GMAIL_ID_CLIENT if username is None else username
        self.password = settings.GMAIL_SECRET_CLIENT if password is None else password
        if not self.username or "@" not in self.username:
            raise ValueError("GMAIL_ID_CLIENT must contain the Gmail sender address")
        if not self.password:
            raise ValueError("GMAIL_SECRET_CLIENT must contain the Gmail app password")

    def send(self, notification: MatchingProfessionalEmail, *, operation_id: str) -> None:
        message = EmailMessage()
        message["From"] = self.username
        message["To"] = notification.recipient
        message["Subject"] = notification.subject
        digest = sha256(operation_id.encode("utf-8")).hexdigest()
        message["Message-ID"] = f"<{digest}@{self.username.rsplit('@', 1)[1]}>"
        message.set_content(notification.body)

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            self.host,
            self.port,
            context=context,
            timeout=self.timeout,
        ) as smtp:
            smtp.login(self.username, self.password)
            refused = smtp.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
