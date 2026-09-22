# API e worker independentes

## Execução

- `uv run app`: FastAPI/Uvicorn; um processo, sem agente ou consumidor em background.
- `uv run app-worker`: um processo com rotinas de entrada, saída e outbox.
- `docker compose up -d --build`: mesma imagem para API, worker e migration.
- Migrations rodam no serviço `migrate` antes da API/worker; não a cada processo.
- `/health` verifica Redis. O worker tem heartbeat com validade de 30 segundos.
- Um advisory lock PostgreSQL impede dois workers simultâneos neste estágio.
  Não escalar réplicas antes de implementar particionamento por conversa.

Apenas WhatsApp está ativo. Dependência, adapters, runners, configuração e testes
específicos do canal retirado foram removidos. Migrations antigas não foram editadas;
a migration nova converte `person.channel` em texto, preservando o histórico.

## Entrada e saída imediata

O webhook extrai e enfileira cada mensagem, mantendo o ID original do provedor.
Só confirma HTTP após Redis aceitar; falhas de Redis propagam erro HTTP.
Mensagens atrasadas não são descartadas apenas por idade. Eventos não suportados
continuam sendo ignorados. Mídia é enfileirada como ID/tipo e resolvida pelo worker.

As filas são Streams, com consumer group, pending entries, confirmação e remoção
atômicas. O worker recupera a entrada pendente mais antiga antes de aceitar outra.
Há até cinco tentativas, com atraso exponencial; erros de infraestrutura Redis
reiniciam o processo e conservam as pendências. Isso preserva ordem, mas um retry
pode atrasar temporariamente outras conversas. A fila de falhas guarda até mil
entradas por direção (`message_queue:{inbound|outbound}:stream:failed`), incluindo
payload, ID original e número de tentativas; as mais antigas saem ao ultrapassar
esse limite. Monitore e exporte falhas antes disso.

A publicação deduplica por ID durante 30 dias. O processamento também registra um
recibo persistente na tabela `inbox`, evitando repetir ações mesmo após essa janela.
O registro contém o resultado e as mudanças de estado ainda não aplicadas no Redis.

Processamento de uma entrada:

1. Resolver mídia, quando houver.
2. Abrir transação SQL compartilhada pelos repositórios.
3. Registrar pessoa/histórico, verificar atendimento manual e executar ações.
4. Salvar cadastro, intenções de integração e recibo de processamento juntos.
5. Depois do commit SQL, aplicar estado, enfileirar resposta e confirmar entrada
   em uma única transação Redis.

Alterações de estado são acumuladas em memória durante o passo 3, com leitura das
próprias alterações. Um rollback não avança o fluxo. Se houver queda depois do
commit SQL, o recibo permite concluir o passo 5 sem executar novamente as ações.
Uma reentrega posterior não restaura um estado antigo da conversa.

O dispatcher registra histórico/recibo depois do envio e confirma a fila.
`POST /send` agora retorna **202 accepted**, não uma confirmação de entrega.

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

A idempotência do Sheets usa uma coluna extra reservada:

- Pacientes: **G**.
- Profissionais: **O**.

Essas colunas devem estar livres antes do primeiro deploy. Guardam o ID da operação,
junto dos dados na mesma escrita. Uma tentativa repetida localiza o ID e atualiza
sua linha. Não apagar/alterar IDs; a garantia pressupõe este único writer e ausência
de edições concorrentes que desloquem linhas durante uma entrega.

## Limites das garantias

- Não há garantia de exatamente uma entrega em APIs externas: cair depois de o
  provedor aceitar e antes de registrar sucesso pode repetir o envio WhatsApp.
- AOF `everysec` pode perder aproximadamente o último segundo em falha da máquina.
  Streams não substituem persistência/backup. O Redis é configurado sem eviction.
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

O comando move, atomicamente e em FIFO, as listas antigas `*:pending` para Streams.
Preserva `history_id` de entradas que já tinham histórico. Pode ser repetido: listas
vazias não fazem nada. Payload inválido interrompe a migração sem remover a entrada.
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
