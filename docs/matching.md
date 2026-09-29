# Matching independente

Uma Lambda aceita pacientes de qualquer projeto autorizado a invocá-la. Ela consulta
PostgreSQL, cadastra quando necessário, faz matching e **somente escreve** na outbox.
Não recebe IDs/tentativas da outbox nem lê eventos dela. Não há retries de matching.

## Contrato de entrada

Paciente já cadastrado:

```json
{"patient_id": 123}
```

Novo cadastro:

```json
{
  "name": "Ana",
  "phone_number": "5511999999999",
  "channel": "WHATSAPP",
  "birth_date": "1990-01-15",
  "area": "Psicoterapia"
}
```

Nome, telefone, nascimento (ISO YYYY-MM-DD) e área são obrigatórios no cadastro.
Telefone é necessário porque `person.phone_number` é obrigatório no esquema atual;
um nome sozinho não identifica uma pessoa. O channel padrão é WHATSAPP; não se
altera o enum existente. Abordagem e perfil são opcionais e apenas persistidos.
A pessoa é reaproveitada por telefone/channel, sem sobrescrever seu cadastro;
cada envio de dados completos cria uma nova inscrição (`patient`). Para repetir
uma avaliação sem criar outra inscrição, envie o `patient_id` retornado.

Lote (1 a 100 pacientes; aceita mistura de IDs e cadastros):

```json
{"patients": [{"patient_id": 123}, {"patient_id": 124}]}
```

Toda entrada é validada antes de iniciar o lote. Cada paciente tem sua própria
transação. Uma falha de infraestrutura interrompe o lote, preservando as transações
anteriores; não há repetição automática. Consultar os resultados persistidos antes
de reenviar dados de cadastro.

Resposta individual (em lote, `{"results": [...]}`):

```json
{"patient_id": 123, "status": "matched", "slot_id": 8, "cycle_id": 2}
```

Outros resultados: `no_capacity` e `patient_not_found`. Todo resultado grava um
novo evento `matching.completed`, com o mesmo payload e status `pending`, na mesma
transação do cadastro/slot. O worker consome esses resultados pelo relay específico descrito abaixo.
O relay de Sheets e o relay de solicitações do chatbot não consomem esses eventos.

## Regras e concorrência

Algoritmo guloso: área exatamente igual, ciclo iniciado, não cancelado, dentro do
prazo e com vaga. Psicanálise continua separada de Psicoterapia. Valor é ignorado.
A função `compatibility` é um ponto de extensão futuro e retorna sempre zero.
Nenhum gênero, perfil ou abordagem influencia a escolha nesta versão.

Prioriza o deadline mais próximo, com desempate pelo ID do ciclo. Mantém scores de
urgência e a distinção dos sete dias finais para auditoria; com preferências
zeradas, a ordem efetiva é sempre por prazo. Regular e reposição são equivalentes.
Cada `patient_id` recebe no máximo um slot, sem esperar aceite.

Sem capacidade, o paciente permanece sem slot. O agendamento horário processa
até **100 pacientes**, mais antigos primeiro, com capacidade potencial disponível.
Esse limite é da varredura horária, não um bloqueio global das chamadas diretas.
É possível enviar dez pacientes numa mesma invocação.

Validações de negócio ficam no código. A transação bloqueia paciente/ciclo e
revalida a capacidade após esperar os locks. Unicidade e FKs permanecem no banco.
A migration `0010_matching` concentra o schema; não há migration 0011 nem triggers.
Escritas SQL externas não validam área/capacidade automaticamente; devem seguir o
mesmo serviço e protocolo de locks. Alterações futuras de capacidade também devem
bloquear o ciclo e impedir capacidade menor que a ocupação.

## Integração do chatbot

A action de cadastro salva o paciente e solicita matching na outbox da própria
aplicação, na mesma transação. Seu relay chama a Lambda com `{"patient_id": ...}`
e conclui o evento de transporte ao receber a resposta. A Lambda não conhece esse
evento; outros projetos podem invocar o mesmo contrato diretamente, sem outbox de
entrada. Falhas do relay são marcadas `failed`, sem retry automático. Se o processo
cair durante a chamada, o evento passa a `failed` quando o lease expirar, sem reenvio.
Perguntas, mensagens e transições do chatbot não foram alteradas.

## Configuração e deploy

O deploy atualiza uma Lambda **já existente**, sem criar infraestrutura, acessar o
banco ou aplicar migrations. O CD do chatbot aplica `0010_matching` e, quando
termina com sucesso, chama `.github/workflows/matching.yml` com o mesmo commit.
Também é possível executar esse workflow manualmente após o schema estar aplicado.

Usa as credenciais e região AWS já existentes. Só são necessárias estas configurações
específicas do matching:

- `MATCHING_LAMBDA_NAME`: nome da função existente, sem alias/versão (GitHub variable
  ou secret). Também é propagado ao worker do chatbot.
- `MATCHING_DATABASE_URL`: URL PostgreSQL completa, com usuário/senha (GitHub secret).
  O deploy grava essa variável na Lambda e preserva as demais variáveis existentes.

Execução local, com as variáveis exportadas e AWS já autenticada:

```sh
uv run --with pip python -m matching.deploy
```

Não há SAM, template, Secrets Manager, variáveis de subnet/security group nem
verificação de migration no deploy do matching. O script empacota, atualiza o código
e define o handler `matching.handler.handler`. Não altera role, rede, memória,
timeout ou agendamento da função. Configure esses recursos no console: Python 3.13
(também suporta 3.12), pacote ZIP, timeout adequado ao lote (120 s recomendado),
acesso de rede ao PostgreSQL e EventBridge horário se quiser a varredura automática.
Desabilite retries no console para manter a política atual. Use o nome da função;
o script não atualiza aliases ou versões publicadas.

O runtime e a arquitetura são lidos da função existente para selecionar os wheels
compatíveis. O ZIP inclui `matching`, os modelos de `app/domain/db`, enums e
`app/domain/matching`, sem inicializar API, Redis ou configuração do chatbot.
`pgvector` é incluído porque o registro de modelos compartilhados também importa
os modelos de FAQ. O handler valida JSON e converte para dataclasses; serviço e
algoritmo trabalham com tipos explícitos. PostgreSQL continua sendo a fonte de verdade.

## Outbox genérica

`claim(kinds=..., max_attempts=...)` seleciona e bloqueia apenas os tipos informados,
com `FOR UPDATE SKIP LOCKED` e lease de cinco minutos. Eventos com lease vencido
são recuperados se ainda há tentativas; caso contrário são marcados `failed`.
`finish(..., max_attempts=...)` aplica o limite informado pelo consumidor e protege
contra conclusão de uma tentativa antiga. O repositório não conhece matching/Sheets.
Sheets informa seus dois tipos e usa cinco tentativas. Matching informa
`matching.requested` e limite de uma tentativa, tanto no claim quanto no finish.

## Testes

Uma única URL serve aos testes PostgreSQL de entrega e matching:

```sh
PYTHON_DOTENV_DISABLED=1 pytest tests/matching -q
DELIVERY_TEST_DATABASE_URL='postgresql+psycopg://...' PYTHON_DOTENV_DISABLED=1 pytest tests/matching tests/delivery -q
python -m matching.simulate --seeds 100 --professionals 50 --patients 500
```

A URL deve apontar para PostgreSQL descartável com permissão para criar bancos
temporários. Os testes de entrega também usam `DELIVERY_TEST_REDIS_URL` para Redis.
Sem essas configurações, os respectivos testes de integração são pulados.
Os testes de domínio recebem relógio controlado; não dependem da data atual.

Para verificar somente o pacote, sem AWS:

```sh
uv run --with pip python -m matching.package --output /tmp/matching.zip
```

A credencial de deploy precisa de `lambda:GetFunctionConfiguration`,
`lambda:UpdateFunctionCode` e `lambda:UpdateFunctionConfiguration` na função.
O worker continua precisando apenas de `lambda:InvokeFunction`. O deploy usa as
APIs [UpdateFunctionCode](https://docs.aws.amazon.com/lambda/latest/api/API_UpdateFunctionCode.html)
e [UpdateFunctionConfiguration](https://docs.aws.amazon.com/cli/latest/reference/lambda/update-function-configuration.html),
sem criar recursos nem acessar o banco.

## Notificação direta pelo WhatsApp

O worker possui um relay exclusivo para `matching.completed`, com cinco tentativas,
lease e claim do OutboxRepository. Processa um evento por vez e não usa Redis nem
cria Message na fila outbound. O matching inclui no JSON do evento `patient_phone`,
`professional_name`, `professional_area` e `professional_phone`, além de `patient_id`,
`slot_id` e `cycle_id` para auditoria. Esse snapshot é gravado na mesma transação
da alocação, inclusive quando o paciente já possui slot. Contatos ausentes impedem
a transação de publicar um resultado incompleto.

Para `matched`, o relay constrói o template diretamente do snapshot, sem consultar
cadastros, slots ou ciclos. Alterações posteriores nos cadastros não mudam o evento.
Payloads incompletos (inclusive eventos antigos contendo apenas IDs) falham e seguem
o retry da outbox; não existe fallback de consulta ao banco.

A dataclass `MatchingPatientTemplate` define `matching_paciente`, idioma `pt_BR` e
os parâmetros do body, nesta ordem: nome do profissional, área, link
`https://wa.me/<telefone internacional do profissional>`. Não contém o texto do
template. Telefones são normalizados sem inventar DDI; precisam estar cadastrados
com código de país. O adapter expõe `send_template` e exige resposta HTTP bem-sucedida
com message ID antes de o relay concluir o evento.

`no_capacity` e `patient_not_found` são concluídos sem mensagem. Qualquer outro
status é erro. Após cinco falhas, o evento fica `failed`. O template usa as mesmas
variáveis WHATSAPP_ACCESS_TOKEN e WHATSAPP_PHONE_NUMBER_ID; não requer variáveis
novas, e seu nome/idioma permanecem fixos conforme o contrato.

A idempotência da outbox é por evento: eventos concluídos não são consumidos de
novo; claims concorrentes respeitam SKIP LOCKED e o lease. Como o POST externo e
a conclusão no PostgreSQL não são uma transação única, uma queda depois de o
WhatsApp aceitar a mensagem e antes do finish pode gerar reenvio na recuperação.
Não há promessa de exactly-once na API externa nem campos novos na outbox.
