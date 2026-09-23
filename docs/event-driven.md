# API e worker independentes

## Execução

- `uv run app`: FastAPI/Uvicorn; um processo, sem agente ou consumidor em background.
- `uv run app-worker`: um processo com rotinas de entrada, saída e outbox.
- `docker compose up -d --build`: mesma imagem para API, worker e migration.
- Migrations rodam no serviço `migrate` antes da API/worker; não a cada processo.
- `/health` verifica Redis. O worker tem heartbeat com validade de 30 segundos.
- Um advisory lock PostgreSQL impede dois workers simultâneos neste estágio.
  Não escalar réplicas antes de implementar particionamento por conversa.

Apenas WhatsApp tem integração ativa. `Channel` e `person.channel` continuam enums,
incluindo o valor histórico TELEGRAM. A migration 0009 apenas cria inbox/outbox.

## Entrada, retenção e ordenação

O webhook salva **toda mensagem recebida** no PostgreSQL, inclusive mensagens antigas.
O recibo `received:{event_id}` evita histórico duplicado e conserva o payload original
(incluindo referência à mídia). `history_id` é usado pelo FAQ para associar a pergunta
à tabela de histórico, portanto permanece no modelo.

Somente mensagens com timestamp do WhatsApp de até cinco minutos entram no inbound.
Sem timestamp, com timestamp futuro ou vencidas: ficam no banco e não são respondidas.
A fila remove mensagens que vencem enquanto esperam; o dispatcher também confere a
idade antes do envio. Respostas preservam o timestamp da mensagem que as originou.

`app/infra/message_queue.py` usa sorted sets e registros Redis. A seleção considera
primeiro o menor timestamp **disponível no Redis** de cada chat. A mensagem reserva
seu chat enquanto está em processamento. Em falha, `available_at` recebe a data da
próxima tentativa, sem sleep no caminho de retry: outros chats continuam elegíveis,
e as seguintes daquele chat aguardam sua primeira mensagem. Eventos que chegam depois
de outro já processado não podem ser reordenados retroativamente.

Limites automáticos:

- 512 mensagens por fila; cheia produz erro, sem apagar uma mensagem válida.
- Mensagens deixam de ser elegíveis após cinco minutos; expurgadas em cada acesso.
- 512 recibos de conclusão por fila, válidos por até uma hora.
- 1.024 registros de contexto/draft no total; os de expiração mais próxima são
  removidos ao exceder o limite. Todos possuem TTL de no máximo uma hora.
- Payloads/estados Redis limitados a 16 KiB cada.
- Nenhuma fila de falhas permanente no Redis: o histórico recebido permanece no SQL.

Não é preciso observar Redis para efetuar limpeza. Falhas de infraestrutura reiniciam
o worker; na inicialização ele libera reservas abandonadas e preserva os prazos dos
retries. Há no máximo cinco tentativas antes de abandonar o processamento automático.

Cadastro, outbox e recibo de processamento usam uma transação SQL compartilhada.
As mudanças do contexto são acumuladas até o commit; estado, resposta e conclusão da
entrada são então aplicados atomicamente no Redis. O histórico já foi persistido pelo
webhook antes disso. Falha na publicação não perde o histórico e permite reentrega.

`POST /send` retorna **202 accepted**, não uma confirmação de entrega.
A factory de mídia fica em `app/infra/media_factory.py`. `WhatsAppMediaService.download`
retorna bytes e MIME; `S3MediaService` se limita ao armazenamento/leitura no S3.

## Outbox

Tabela persistente `outbox`, sem colunas específicas de fornecedor:

| Coluna | Finalidade |
| --- | --- |
| `id` | Chave estável da operação; PK e deduplicação |
| `kind` | Operação versionada, que seleciona o handler |
| `payload` | JSONB com os dados necessários à entrega |
| `status` | pending, processing, sent, failed |
| `available_at` | Data programada ou próxima tentativa |
| `attempts` | Número de tentativas e versão da reserva |
| `locked_until` | Validade da reserva |
| `last_error` | Classe da última falha; detalhes no log |
| `created_at` | Criação/retencão |

`OutboxRepository.enqueue` exige transação de negócio ativa. Não abre um segundo
commit. Os pontos existentes de cadastro de paciente/profissional geram a operação
Sheets na mesma transação das alterações SQL. Cadastro de retorno mantém o
comportamento anterior: não gera uma nova linha Sheets.

Uma única thread possui o cliente Google. Reserva com `FOR UPDATE SKIP LOCKED`
em transação curta; entrega fora dela; finaliza conferindo `id` e `attempts`.
Reservas vencem em cinco minutos. HTTP Google tem timeout de 30 segundos por chamada.
Falhas têm até cinco tentativas e atraso crescente, permanecendo `failed` no banco
quando esgotadas. Linhas `sent` criadas há mais de 30 dias são limpas periodicamente.

Handlers disponíveis: `sheets.patient.upsert.v1` e
`sheets.professional.upsert.v1`. E-mail e WhatsApp programado ainda precisam de
handlers; a tabela já comporta os dados e o agendamento por `available_at`.
Tipos sem handler falham visivelmente, sem serem marcados como enviados.

A deduplicação do Sheets usa **developer metadata**, sem gravar IDs nas colunas
G/O. Dados e metadata são criados em um único `batchUpdate`; em uma tentativa
repetida, a metadata indica que a operação já foi aplicada. As colunas originais
A:F e A:N são preservadas. IDs escritos por versões anteriores não são apagados
automaticamente de planilhas reais por esta alteração de código.

## Limites das garantias

- Não há garantia de exatamente uma entrega em APIs externas: cair depois de o
  provedor aceitar e antes de registrar sucesso pode repetir o envio WhatsApp.
- AOF `everysec` pode perder aproximadamente o último segundo em falha da máquina.
  O agendador não substitui persistência/backup. O Redis é configurado sem eviction.
- SQL e Redis não participam de uma transação distribuída. Os recibos e o protocolo
  de recuperação cobrem quedas normais entre etapas; não resolvem restaurações
  independentes de backups inconsistentes dos dois serviços.
- `inbox` conserva recibos para deduplicação. Seu crescimento em disco deve ser
  acompanhado; uma futura política de retenção precisa respeitar o prazo de replay.
- Históricos/estado e payloads de mídia podem aumentar memória sob carga. A imagem
  pequena não equivale a baixo consumo de RAM.

## Primeira migração do deploy antigo

1. Construir a nova imagem.
2. Parar API/worker e a aplicação antiga antes de mexer nas filas.
3. Aplicar `alembic upgrade head` pelo serviço `migrate`.
4. Executar `docker compose run --rm --no-deps api python -m app.migrate_queues`.
5. Iniciar API e worker com `docker compose up -d --remove-orphans api worker`.

O comando arquiva entradas das listas/Streams antigos e publica somente as recentes
no novo agendador. Preserva histórico existente, remove a origem após publicação e
aplica os limites de retenção aos contextos antigos. Payload inválido interrompe a
migração sem remover a entrada. Executar com todos os consumidores parados.
Verificar previamente pendências do canal removido: não serão consumidas como WhatsApp.
O workflow de deploy executa essa sequência. Não subir a versão antiga e a nova juntas.

## Validação

`uv run ruff check .`, `uv run mypy .`, `uv run pytest -q`.

Os testes em `tests/delivery` exigem infraestrutura isolada explicitamente indicada:

```bash
PYTHON_DOTENV_DISABLED=1 \
DELIVERY_TEST_REDIS_URL=redis://localhost:16389/0 \
DELIVERY_TEST_DATABASE_URL=postgresql+psycopg://chatbot:test-only-password@localhost:15489/chatbot \
uv run pytest tests/delivery -q
```

Criam e removem schemas PostgreSQL exclusivos; não apontar para produção. O CI usa
serviços efêmeros, executa esses testes e sobe a imagem com ambos os processos.
