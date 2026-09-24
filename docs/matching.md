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
transação do cadastro/slot. Um consumidor externo poderá entregar esses resultados.
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
A migration 0011 remove triggers também em instalações que já aplicaram 0010.
Escritas SQL externas não validam área/capacidade automaticamente; devem seguir o
mesmo serviço e protocolo de locks. Alterações futuras de capacidade também devem
bloquear o ciclo e impedir capacidade menor que a ocupação.

## Integração do chatbot

A action de cadastro salva o paciente e solicita matching na outbox da própria
aplicação, na mesma transação. Seu relay chama a Lambda com `{"patient_id": ...}`
e conclui o evento de transporte ao receber a resposta. A Lambda não conhece esse
evento; outros projetos podem invocar o mesmo contrato diretamente, sem outbox de
entrada. Falhas do relay são marcadas `failed`, sem retry automático. Se o processo
cair durante a chamada, o evento pode permanecer `processing`, exigindo inspeção.
Perguntas, mensagens e transições do chatbot não foram alteradas.

## Configuração e deploy

As variáveis estão em `.env.example`:

- `MATCHING_LAMBDA_NAME`: nome/ARN do alias para o worker.
- `AWS_REGION`: região usada pelo worker; o SDK também aceita AWS_DEFAULT_REGION.
- `MATCHING_DATABASE_URL`: conexão PostgreSQL da Lambda, para configuração direta/local.
- `DATABASE_SECRET_ARN`: alternativa na Lambda; secret JSON `{"url": "postgresql+psycopg://..."}`.
- `MATCHING_TEST_DATABASE_URL`: PostgreSQL descartável para os testes reais.

Não é preciso configurar a URL do banco da Lambda no worker. Em AWS, o template
usa Secrets Manager e uma role dedicada. A role precisa SELECT nas tabelas de
cadastro/matching, INSERT em person/patient/matching_slot/outbox, acesso às sequências
e UPDATE nas tabelas bloqueadas por row locks. Nenhum SELECT na outbox é necessário.

1. Aplicar `alembic upgrade head` pelo migrador existente. O schema requerido é
   `0011_remove_matching_triggers`. A migration 0010 não descarta vínculos antigos
   de `professional_patient` se a tabela estiver preenchida.
2. Configurar rede privada Lambda → PostgreSQL no Lightsail, firewall/pg_hba e TLS.
   O hostname Docker `postgres` não é resolvido pela Lambda. A VPC também precisa
   alcançar Secrets Manager (endpoint privado ou saída de rede).
3. Executar `sam validate --lint --template deploy/matching/template.yaml`,
   `sam build --use-container --template-file deploy/matching/template.yaml` e
   `sam deploy --guided`. Uma função, alias live, memória 256 MB, concorrência 2.
4. Configurar `MATCHING_LAMBDA_NAME` no worker e permissão IAM lambda:InvokeFunction
   sobre o alias. APIs externas autenticadas usam o mesmo contrato; não expor
   credenciais AWS no navegador. Não existe Function URL pública.

CD separado em `.github/workflows/matching.yml`: environment matching-production,
OIDC, vars MATCHING_DEPLOY_ROLE_ARN, AWS_REGION, MATCHING_DATABASE_SECRET_ARN,
MATCHING_SUBNET_IDS, MATCHING_SECURITY_GROUP_IDS e MATCHING_SCHEMA_REVISION.
A última variável deve ser atualizada somente após aplicar a migration. Não é
uma verificação remota do banco. Não executar migrations no handler.

## Testes

```sh
PYTHON_DOTENV_DISABLED=1 pytest tests/matching -q
MATCHING_TEST_DATABASE_URL='postgresql+psycopg://...' PYTHON_DOTENV_DISABLED=1 pytest tests/matching -q
python -m matching.simulate --seeds 100 --professionals 50 --patients 500
```

A URL de integração deve apontar para banco descartável com permissão de criar
bancos temporários. Sem ela, os testes PostgreSQL são explicitamente pulados.
Os testes de domínio recebem um relógio controlado, com datas em diferentes anos;
não dependem do dia em que pytest é executado. Os testes de integração usam o
relógio do próprio PostgreSQL para montar ciclos relativos ao instante do teste.
