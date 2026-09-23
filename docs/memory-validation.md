# Verificação de memória — 22/09/2026

> Relatório histórico anterior às correções de 23/09 (novo agendador e metadata no Sheets).
> Não representa uma medição refeita da versão atual.

## Resultado observado

Teste local Linux, Docker Engine 29.8.1, imagem Python 3.13 slim, um processo API e
um processo worker. Após 2.000 webhooks (1.000 mensagens únicas, cada uma repetida):

| Serviço | RAM observada (`docker stats`) |
| --- | ---: |
| API | 91,8 MiB |
| Worker | 116,7 MiB |
| API + worker | **208,5 MiB (~219 MB)** |
| Redis | 5,8 MiB |
| PostgreSQL | 53,0 MiB |
| Conjunto dos quatro | **267,4 MiB (~280 MB)** |

Picos registrados pelo cgroup: API 101.900.288 bytes e worker 127.029.248 bytes.
Somar esses máximos individuais resulta em cerca de 218,3 MiB; eles não precisam
ter ocorrido ao mesmo tempo. O pico do cgroup inclui memória que `docker stats`
pode descontar como cache. Não houve eventos OOM ou processos mortos por memória.

Também foram impostos limites de 110 MiB para API e 140 MiB para worker, sem swap,
no teste de 2.000 webhooks. Esses limites somam 250 MiB, não 250 MB decimais.

**A aplicação coube no cenário de texto; os quatro serviços juntos ultrapassaram
250 MB. Não considerar isto uma garantia de capacidade de produção.**

## O que foi exercitado

- Processos em containers separados, mesma imagem.
- API HTTP real, Redis e PostgreSQL reais, migrations aplicadas.
- 1.000 cadastros na etapa final do fluxo de paciente.
- 1.000 recibos únicos, respostas e entregas de outbox, apesar dos 2.000 webhooks.
- S3/Boto3 inicializado com credenciais fictícias.
- Cliente OpenAI inicializado; cliente Google com a autenticação substituída.
- Chamadas externas substituídas por respostas locais; nenhum envio real foi feito.
- Testes adicionais cobrem rollback, reentrega após commit SQL, reserva vencida,
  envio deduplicado, mensagem inválida e migração de filas antigas.

Não foram medidos vídeos/documentos grandes, inferência real, variações da rede,
planilhas grandes ou operação por várias horas. O caminho atual de mídia ainda
carrega arquivos em memória: mídia grande pode estourar a margem. A memória da
máquina inclui também sistema operacional/Docker/outros serviços.

## Reduções aplicadas

O primeiro teste com o cliente de descoberta do Google ultrapassou 500 MiB no worker.
Reutilizar seus recursos reduziu esse número, mas API + worker ainda excediam 250 MiB.
O serviço agora usa HTTP REST com `google-auth`/`AuthorizedSession`, sem carregar os
grafos dinâmicos de descoberta. O cliente autenticado é reutilizado por uma thread.
Autenticação continua usando a mesma service account e os mesmos scopes.

Referências do transporte e API:
[AuthorizedSession](https://google-auth.readthedocs.io/en/latest/reference/google.auth.transport.requests.html),
[Sheets REST](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values/update).

Outras medidas: um processo por serviço, imports do SDK OpenAI adiados até uso,
executor limitado, pools SQL limitados, lotes unitários e probe do worker com apenas
biblioteca padrão. A imagem de execução não leva ferramentas de desenvolvimento,
cache de instalação, segredos ou caches locais. Imagem medida: ~418 MB em disco;
isso não equivale ao consumo de RAM, e os dois containers compartilham a imagem.

## Reproduzir sem credenciais reais

A configuração `docker-compose.validation.yml` é independente da de produção.
Usa portas locais exclusivas e não lê `.env`. Não executar contra banco/Redis reais.

```bash
docker compose -p chatbot-event-test -f docker-compose.validation.yml up -d redis postgres
docker compose -p chatbot-event-test -f docker-compose.validation.yml build api
docker compose -p chatbot-event-test -f docker-compose.validation.yml run --rm api alembic upgrade head
docker compose -p chatbot-event-test -f docker-compose.validation.yml up -d api worker

PYTHONPATH=. PYTHON_DOTENV_DISABLED=1 DELIVERY_RUNTIME_TEST=1 \
DELIVERY_TEST_COUNT=1000 \
DELIVERY_TEST_API_URL=http://127.0.0.1:18089 \
DELIVERY_TEST_REDIS_URL=redis://127.0.0.1:16389/0 \
DELIVERY_TEST_DATABASE_URL=postgresql+psycopg://chatbot:test-only-password@127.0.0.1:15489/chatbot \
uv run python tests/runtime_load.py

docker stats --no-stream chatbot-event-test-api-1 chatbot-event-test-worker-1 \
  chatbot-event-test-redis-1 chatbot-event-test-postgres-1

docker compose -p chatbot-event-test -f docker-compose.validation.yml down -v
```

`tests/runtime_worker.py` é exclusivamente um executor de teste: substitui WhatsApp
 e Sheets por implementações locais. Não usar esse comando no deploy.

Não foram impostos limites rígidos no Compose de produção: escolher os limites
finais depois de medir mídia e integrações reais, incluindo os probes e a margem
da máquina. Dois processos no mesmo container continuam carregando dois runtimes;
um protocolo de IPC por si só não remove o consumo das bibliotecas e dos bancos.
