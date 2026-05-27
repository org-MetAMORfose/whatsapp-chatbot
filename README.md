# Metamorfose WhatsApp Chatbot (FastAPI)

## Visao geral

Scaffold de backend para o chatbot de WhatsApp da Metamorfose, construído com **FastAPI**.

## Requisitos

- Python 3.11+
- `uv`

Se quiser saber como instalar o `uv`, consulte a documentação oficial:
https://docs.astral.sh/uv/

## Setup com uv

1. Crie e ative o ambiente virtual:

```bash
uv venv .venv
source .venv/bin/activate
```

2. Instale as dependências do projeto:

```bash
uv sync --dev
```

3. Configure as variáveis de ambiente:

```bash
cp .env.example .env
```

## Executar localmente

```bash
uv run app
```

## Executar com Docker

```bash
docker build -t app .
docker run -p 8000:8000 app
```

## Testes

```bash
uv run pytest
```

## Checagens de qualidade

Execute tudo em um comando:

```bash
uv run ruff check . && uv run mypy . && uv run pytest
```

## Pre-commit

Instale e habilite o hook:

```bash
uv run pre-commit install
```

Execute manualmente:

```bash
uv run pre-commit run --all-files
```

> Os hooks de pre-commit executam **ruff**, **mypy** e **pytest** antes de cada commit.

---

## Armazenamento de mídia no S3

Imagens e documentos recebidos via WhatsApp são automaticamente baixados da WhatsApp Media API e armazenados no Amazon S3 antes de serem processados pelos services. O `MessageHistoryModel` passa a salvar a URL S3 nos campos `image_url` e `document_url` em vez do media ID temporário do WhatsApp.

### Variáveis de ambiente necessárias

Adicione ao seu `.env`:

```env
AWS_ACCESS_KEY_ID=sua_access_key
AWS_SECRET_ACCESS_KEY=sua_secret_key
AWS_REGION=us-east-1
S3_BUCKET_NAME=nome-do-seu-bucket
```

> Se `S3_BUCKET_NAME` não estiver configurado, o comportamento anterior é mantido (salva o media ID do WhatsApp sem fazer upload).

### Fluxo de mídia recebida

```
WhatsApp Webhook (imagem/documento)
    ↓
WhatsAppController._parse_message()        # extrai o media ID
    ↓
WhatsAppController._resolve_media()        # novo
    ├─ GET /v23.0/{media_id}               # obtém URL de download
    ├─ GET {url}                           # baixa o binário
    └─ S3.put_object(key, bytes)           # faz upload ao S3
    ↓
Message.image / Message.document = URL S3
    ↓
MessageReceiverService.handle()            # salva URL S3 no banco
```

### Endpoint `/send` — envio de mídia

O endpoint `POST /send` aceita agora campos opcionais para enviar imagens e documentos:

```json
{
  "phone_number": "5511999999999",
  "content": "Segue o documento",
  "image_url": "https://bucket.s3.region.amazonaws.com/media/image/abc.jpg",
  "document_url": null
}
```

Todos os campos são opcionais exceto `phone_number`.

### Arquivos alterados

| Arquivo | Alteração |
|---|---|
| `app/services/s3_media_service.py` | Novo serviço — download da WhatsApp API + upload S3 |
| `app/config/settings.py` | Novas vars `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME` |
| `app/controllers/whatsapp_controller.py` | Injeta `S3MediaService`; resolve mídia antes do receiver |
| `app/controllers/send_message_controller.py` | Campos `image_url` e `document_url` opcionais no request |
| `app/runners/whatsapp_runner.py` | Instancia e injeta `S3MediaService` no controller |
| `pyproject.toml` | Dependência `boto3>=1.34.0` adicionada |
