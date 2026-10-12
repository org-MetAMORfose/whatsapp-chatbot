import smtplib
from unittest.mock import MagicMock, patch

import pytest

from app.services.email_service import GmailSmtpAdapter, MatchingProfessionalEmail


def notification() -> MatchingProfessionalEmail:
    return MatchingProfessionalEmail(
        recipient="profissional@example.com",
        patient_name="Ana",
        patient_area="Psicoterapia",
        patient_phone="+55 (11) 99999-9999",
    )


@patch("app.services.email_service.smtplib.SMTP_SSL")
def test_sends_utf8_plain_text_with_stable_message_id(smtp_class: MagicMock) -> None:
    smtp = smtp_class.return_value.__enter__.return_value
    smtp.send_message.return_value = {}
    adapter = GmailSmtpAdapter("remetente@gmail.com", "app-password")

    adapter.send(notification(), operation_id="matching:professional-email:123")

    smtp.login.assert_called_once_with("remetente@gmail.com", "app-password")
    message = smtp.send_message.call_args.args[0]
    assert message["From"] == "remetente@gmail.com"
    assert message["To"] == "profissional@example.com"
    assert message["Subject"] == "Novo paciente pela MetAMORfose"
    assert message.get_content().strip() == (
        "Olá, tudo bem?\n\n"
        "Você recebeu uma nova conexão com paciente pela MetAMORfose.\n\n"
        "👤 Paciente: Ana\n"
        "📋 Área: Psicoterapia\n"
        "Contato do paciente:\n"
        "https://wa.me/5511999999999\n\n"
        "Este envio é referente ao seu ciclo de atendimento ativo.\n\n"
        "Consulte nosso guia de como conversar com o paciente:\n"
        "http://orgmetamorfose.com.br/manual-de-uso\n\n"
        "Caso precise de suporte:\n"
        "https://wa.me/5511958048414"
    )
    first_message_id = message["Message-ID"]

    smtp.reset_mock()
    adapter.send(notification(), operation_id="matching:professional-email:123")
    assert smtp.send_message.call_args.args[0]["Message-ID"] == first_message_id


@patch("app.services.email_service.smtplib.SMTP_SSL")
def test_refused_recipient_is_a_delivery_failure(smtp_class: MagicMock) -> None:
    smtp = smtp_class.return_value.__enter__.return_value
    smtp.send_message.return_value = {
        "profissional@example.com": (550, b"recipient rejected")
    }
    adapter = GmailSmtpAdapter("remetente@gmail.com", "app-password")

    with pytest.raises(smtplib.SMTPRecipientsRefused):
        adapter.send(notification(), operation_id="event")


@pytest.mark.parametrize(
    ("username", "password"),
    [("", "password"), ("not-an-email", "password"), ("sender@gmail.com", "")],
)
def test_rejects_missing_smtp_configuration(username: str, password: str) -> None:
    with pytest.raises(ValueError):
        GmailSmtpAdapter(username, password)
