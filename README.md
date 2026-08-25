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

## Migrations de banco

Use migrations quando alterar qualquer model em `app/domain/db`.

O fluxo normal é:

1. Altere os models em `app/domain/db`.
2. Crie a migration:

```bash
uv run alembic revision --autogenerate -m "descricao da mudanca"
```

3. Revise o arquivo gerado em `migrations/versions`.
4. Suba o Docker Compose para testar. O app aplica a migration automaticamente antes de iniciar:

```bash
docker compose up -d --build
```

5. Se tudo estiver certo, commite o model e o arquivo novo em `migrations/versions`.

Se quiser aplicar a migration manualmente, use:

```bash
uv run alembic upgrade head
```

> O Docker Compose aplica migrations existentes, mas não cria migrations novas. Sempre gere e commite o arquivo em `migrations/versions` antes de abrir o PR.

Para bancos já existentes criados antes do Alembic, rode uma única vez:

```bash
uv run alembic stamp 0001_baseline_schema
uv run alembic upgrade head
```

## Midias no S3

O bucket de midias permanece privado. A aplicacao persiste somente a chave do
objeto, por exemplo:

```text
media/image/21842910.png
media/document/4234234.pdf
media/video/9876543.mp4
```

O endpoint `POST /upload-media` retorna essa chave no campo `media`, e o
endpoint `POST /send` recebe a mesma chave no campo `media`. URLs completas ou
pre-assinadas nao sao persistidas.

Um backend que precise exibir os arquivos deve receber permissao `s3:GetObject`
restrita ao prefixo `media/*`, preferencialmente por IAM Role. O navegador nao
deve receber credenciais AWS; o backend do frontend pode transmitir o arquivo
ou gerar uma URL temporaria somente no momento da leitura.

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
