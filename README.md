# Metamorfose WhatsApp Chatbot (FastAPI)

## Overview

Backend scaffold for Metamorfose WhatsApp chatbot using **FastAPI**.

## Setup

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies and configure environment:

```bash
pip install -r requirements.txt
cp .env.example .env
```

## Run locally

```bash
uvicorn app.main:app --reload
```

## Run with Docker

```bash
docker build -t app .
docker run -p 8000:8000 app
```

## Tests

```bash
pytest
```

## Quality checks

Run all checks in one command:

```bash
ruff check . && mypy . && pytest
```

## Pre-commit

Install and enable the Git hook:

```bash
pip install pre-commit
pre-commit install
```

Run manually:

```bash
pre-commit run --all-files
```

> The pre-commit hooks run **ruff**, **mypy**, and **pytest** before each commit.
