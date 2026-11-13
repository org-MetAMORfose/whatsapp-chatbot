"""Registra no Banco do Brasil a URL do webhook Pix deste ambiente.

Uso (no servidor, com o .env de produção): `python scripts/registrar_webhook_pix.py`
"""
import asyncio
import sys

import app.config.settings as settings
from app.services.pix.banco_do_brasil import BancoDoBrasilPixGateway
from app.services.pix.gateway import pix_gateway_from_settings


async def main() -> int:
    if not settings.PUBLIC_BASE_URL or not settings.PIX_WEBHOOK_TOKEN:
        print("Defina PUBLIC_BASE_URL e PIX_WEBHOOK_TOKEN antes de registrar o webhook.")
        return 1
    gateway = pix_gateway_from_settings()
    if not isinstance(gateway, BancoDoBrasilPixGateway):
        print("PIX_PROVIDER precisa ser 'bb' para registrar o webhook no Banco do Brasil.")
        return 1
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/pix/webhook/{settings.PIX_WEBHOOK_TOKEN}"
    await gateway.register_webhook(url)
    print(f"Webhook registrado para a chave {settings.BB_PIX_CHAVE}: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
