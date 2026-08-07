#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
PHONE_NUMBER="${PHONE_NUMBER:-11939016277}"

if [[ ! -f .env ]]; then
  echo "Arquivo .env não encontrado na raiz do projeto. Rode: cp .env.example .env"
  exit 1
fi

set -a
source .env
set +a

if [[ -z "${REDIS_PASSWORD:-}" ]]; then
  echo "Variável REDIS_PASSWORD não encontrada no .env"
  exit 1
fi

send_message() {
  local content="$1"
  local payload
  payload=$(printf '{"phone_number":"%s","content":"%s"}' "$PHONE_NUMBER" "$content")

  echo "[send] $content"
  curl -sS -X POST "$BASE_URL/send" \
    -H 'Content-Type: application/json' \
    --data "$payload"
  echo
}

echo "== Fluxo de teste: dúvidas =="
echo "Base URL: $BASE_URL"
echo "Telefone: $PHONE_NUMBER"
echo "Dica: se você está rodando o app localmente, ajuste REDIS_HOST/REDIS_PORT e DATABASE_URL para localhost antes de iniciar."
echo

send_message "oi"
send_message "sou profissional"
send_message "duvidas"
echo

echo "== Verificação do estado do contato =="

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -qx 'chatbot-postgres'; then
    echo "[db] chat_mode esperado: MANUAL"
    docker exec chatbot-postgres psql -U "${POSTGRES_USER:-chatbot}" -d "${POSTGRES_DB:-chatbot}" \
      -c "select id, phone_number, chat_mode from person where phone_number='${PHONE_NUMBER}' order by id desc limit 1;"
  else
    echo "[db] container 'chatbot-postgres' não está rodando"
  fi
else
  echo "[db] docker não encontrado no PATH"
fi

echo

if command -v docker >/dev/null 2>&1; then
  if docker ps --format '{{.Names}}' | grep -qx 'chatbot-redis'; then
    echo "[redis] contexto esperado para o estado faq_inicio"
    docker exec chatbot-redis redis-cli -a "${REDIS_PASSWORD}" GET "chat_context:WHATSAPP:${PHONE_NUMBER}"
  else
    echo "[redis] container 'chatbot-redis' não está rodando"
  fi
else
  echo "[redis] docker não encontrado no PATH"
fi
