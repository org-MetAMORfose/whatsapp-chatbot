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
uv run uvicorn app.main:app --reload
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
