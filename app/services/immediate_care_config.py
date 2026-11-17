"""Whether immediate care is really on: the switch plus everything it needs in production.

A switch turned on with a missing secret does not crash the API or the worker (a restart loop
would take the whole bot down): the feature stays closed and the problems are logged as critical.
"""
from __future__ import annotations

import hashlib
import logging

import app.config.settings as settings

logger = logging.getLogger(__name__)
GRAPH_URL = "https://graph.facebook.com"
# SHA-256 of CHATBOT_API_KEY values that were published (Front-adm .env.example). The key guards the endpoint
# that releases psychologists, so a published one keeps immediate care closed until it is replaced.
PUBLISHED_API_KEY_HASHES = frozenset({"fb4c61c6d476fc2b2690f690815b4a26d024024e289b9a3b8d1ee8c285787ae6"})


def configuration_problems() -> list[str]:
    """What is missing to open immediate care to real patients; empty when the switch is off."""
    if not settings.IMMEDIATE_CARE_ENABLED or settings.IMMEDIATE_ALLOW_FAKE:
        return []
    problems: list[str] = []
    if settings.PIX_PROVIDER.strip().lower() != "bb":
        problems.append("PIX_PROVIDER=bb (com o Pix simulado o paciente receberia um código falso)")
    for name in ("BB_PIX_CLIENT_ID", "BB_PIX_CLIENT_SECRET", "BB_PIX_DEV_APP_KEY", "BB_PIX_CERT_PATH", "BB_PIX_KEY_PATH", "BB_PIX_CHAVE"):
        if not getattr(settings, name):
            problems.append(name)
    if not settings.IMMEDIATE_PRICES_CENTS:
        problems.append("IMMEDIATE_PRICES (formato minutos:centavos separados por vírgula, ex.: 10:3000,20:5000)")
    if not settings.PIX_WEBHOOK_TOKEN:
        problems.append("PIX_WEBHOOK_TOKEN")
    if not settings.DAILY_API_KEY:
        problems.append("DAILY_API_KEY (sem ela a sala de vídeo seria simulada)")
    if not settings.WHATSAPP_APP_SECRET:
        problems.append("WHATSAPP_APP_SECRET (sem ela qualquer um forja mensagens no webhook, inclusive o Aceitar do psicólogo)")
    if not settings.CHATBOT_API_KEY:
        problems.append("CHATBOT_API_KEY")
    elif hashlib.sha256(settings.CHATBOT_API_KEY.encode()).hexdigest() in PUBLISHED_API_KEY_HASHES:
        problems.append("CHATBOT_API_KEY nova (a atual foi publicada no .env.example do Front-adm no GitHub)")
    if settings.WHATSAPP_GRAPH_URL.rstrip("/") != GRAPH_URL:
        problems.append(f"WHATSAPP_GRAPH_URL deve ser {GRAPH_URL}")
    return problems


def immediate_care_enabled() -> bool:
    return settings.IMMEDIATE_CARE_ENABLED and not configuration_problems()


def log_configuration() -> None:
    """Called once at startup by the API and the worker."""
    problems = configuration_problems()
    if problems:
        logger.critical(
            "IMMEDIATE_CARE_ENABLED=true, mas o acolhimento imediato continua FECHADO porque falta configurar: %s",
            "; ".join(problems),
        )
    elif settings.IMMEDIATE_CARE_ENABLED:
        logger.info("Acolhimento imediato aberto%s", " (Pix e sala simulados)" if settings.IMMEDIATE_ALLOW_FAKE else "")
