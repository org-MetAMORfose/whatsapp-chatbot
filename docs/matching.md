# Matching

A única fonte de verdade é PostgreSQL. A Lambda lê o paciente já cadastrado e
escreve a alocação em `matching_slot`; não duplica o paciente e não usa Redis.
`matching_cycle` tem capacidade e datas configuradas pelo administrador. A criação
ou edição dos ciclos não é exposta por uma API pública nesta entrega. O código do
matching não abre ciclos automaticamente. `REGULAR` e `REPLACEMENT` são equivalentes.

## Cadastro e critérios

A action `request_matching` é chamada pela action que persiste a nova inscrição,
com o ID exato retornado pelo INSERT, dentro da mesma transação da mensagem.
Também cobre o retorno do paciente. Nenhuma mensagem, pergunta ou transição TOML
foi alterada. Gênero e grupo minorizado já coletados são persistidos no profissional.
Caso o perfil não tenha sido coletado, permanece sem preferência.

Área precisa ser exatamente igual; Psicanálise não equivale a Psicoterapia.
Valor é ignorado. Ter um ciclo iniciado, não cancelado, não vencido e com vaga
habilita o profissional. Cada `patient_id` recebe no máximo um slot; não há aceite.
Sem capacidade, o evento termina com `no_capacity` e o paciente fica sem slot.
A Lambda agendada reavalia até 25 pacientes por hora, priorizando os menos
recentemente tentados. Esse limite é conservador e pode ser aumentado em
`handler.py` após medir duração/carga. O evento de novo cadastro é imediato.

## Algoritmo v1

Abordagem (somente Psicoterapia) e perfil declarado são critérios opcionais.
A similaridade usa blocos categóricos de norma unitária: coincidência contribui 1,
divergência 0; sem preferência não cria dimensão. É equivalente ao cosseno entre
vetores categóricos concatenados. Não usa embeddings nem serviços de IA.
Gênero e identificação racial são dimensões distintas para perfis compostos.
Informação profissional ausente não satisfaz a preferência. Mulheres/homens trans
satisfazem a preferência de gênero correspondente; identidade LGBT explicitamente
informada ou identidade trans satisfaz o perfil LGBTQIAPN+.

`urgency_score = 7 dias / (7 dias + tempo restante)`.
Antes dos sete dias finais, `final_score = compatibility + 0.1 * urgency`.
Nos sete dias finais inclusive, `final_score = 2 + urgency`: primeiro vencimento
mais próximo, depois compatibilidade. O deadline exato já exclui o ciclo.
Desempate final por deadline e ID do ciclo. Não existe limiar mínimo de preferência.
Scores, entradas relevantes, instante da avaliação, operação e versão são guardados
no breakdown. O slot é um registro imutável; o fim do atendimento não devolve vaga.

## Entrega, concorrência e recuperação

O worker tem um relay separado para `matching.requested`. Ele invoca a Lambda de
forma assíncrona e deixa o evento em `processing`. Somente a transação da Lambda
marca `sent`, junto com o slot e o resultado em `outbox.payload.result`.
Bloqueios da outbox, paciente e ciclo, unicidade de `patient_id` e triggers de
capacidade impedem duplicação/overbooking. As consultas usam READ COMMITTED.
A tentativa da outbox cerca eventos atrasados: uma invocação antiga não conclui
uma tentativa nova. Uma falha reverte toda a transação; retries da AWS e recuperação
do lease de cinco minutos repetem o evento. Após cinco claims sem conclusão,
o relay marca `failed`; o agendamento pode solicitar uma nova avaliação.

Resultados `sent` são retidos pela política existente da outbox (30 dias).
O histórico permanente de matches e o ID original da operação ficam no slot,
sem FK para a outbox. Repetir uma solicitação de paciente já alocado retorna seu
slot, inclusive usando outro evento. Eventos antigos apagados retornam unknown_event.
Não há notificação nova ao paciente nesta entrega.

## Preparação e deploy

1. Aplicar `alembic upgrade head` pelo migrador existente. A migration 0010 remove
   `professional_patient` somente se estiver vazia; caso contrário para sem perder
   vínculos, para permitir reconciliação. Não executar migrations no handler.
2. Configurar conectividade privada Lambda → PostgreSQL no Lightsail: VPC/peering,
   subnets, rotas, firewall do host e `pg_hba.conf`. Não usar o hostname Docker
   `postgres` na Lambda. Habilitar TLS no servidor e usar `sslmode=verify-full`
   com certificado confiável. O banco pode continuar no Lightsail.
3. Criar um secret Secrets Manager com JSON `{"url":"postgresql+psycopg://..."}`.
   Usuário da Lambda precisa SELECT em patient/professional/ciclos/slots/outbox,
   INSERT em slots/outbox, UPDATE em outbox e permissões nas sequências. Os row
   locks exigem UPDATE nas tabelas bloqueadas (patient, professional, matching_cycle).
   Use um usuário dedicado, sem permissões de DDL. A Lambda precisa alcançar
   Secrets Manager por endpoint VPC ou saída de rede; não presumir internet em VPC.
4. Instalar AWS CLI e SAM CLI, autenticar na conta, executar:

   ```sh
   sam validate --lint --template deploy/matching/template.yaml
   sam build --use-container --template-file deploy/matching/template.yaml
   sam deploy --guided
   ```

   Informar DatabaseSecretArn, SubnetIds e SecurityGroupIds. Build usa apenas
   `matching/*.py` e suas dependências fixadas, não o chatbot. Memória inicial
   256 MB, timeout 120 s, concorrência máxima 2, uma função e alias `live`.
5. Definir `MATCHING_LAMBDA_NAME` no ambiente do worker com o ARN do alias publicado;
   configurar região/credenciais pelo mecanismo padrão do SDK (`AWS_DEFAULT_REGION`
   ou `AWS_REGION`). Conceder somente `lambda:InvokeFunction` sobre esse alias ao
   principal do worker. Sem essa variável, os eventos ficam pendentes.
6. O workflow `.github/workflows/matching.yml` testa, constrói e publica separadamente.
   Configurar environment `matching-production`, OIDC restrito ao repositório/environment
   e vars: MATCHING_DEPLOY_ROLE_ARN, AWS_REGION, MATCHING_DATABASE_SECRET_ARN,
   MATCHING_SUBNET_IDS, MATCHING_SECURITY_GROUP_IDS. Após a migration, registrar
   MATCHING_SCHEMA_REVISION=0010_matching. Essa marca é uma declaração operacional,
   não uma consulta ao banco; o deploy não tem acesso automático ao banco privado.
   A role de deploy precisa das permissões de CloudFormation, S3, Lambda, IAM/passrole
   e EventBridge necessárias à stack; não é a role do worker.

Não foi feito deploy na conta AWS. Uma futura API administrativa autenticada pode
inserir o mesmo evento na outbox com ID único e `payload.patient_id`; o navegador
não recebe credenciais AWS. Não há Function URL pública. Para rollback, atualizar
o alias para a versão anterior compatível; não apagar o histórico por downgrade.

## Verificação

```sh
PYTHON_DOTENV_DISABLED=1 pytest tests/matching -q
MATCHING_TEST_DATABASE_URL='postgresql+psycopg://...' PYTHON_DOTENV_DISABLED=1 pytest tests/matching -q
python -m matching.simulate --seeds 100 --professionals 50 --patients 500
```

A URL de teste deve apontar para PostgreSQL descartável com permissão de criar
bancos: cada execução cria e remove um banco próprio e aplica todas as migrations.
Os testes reais cobrem competição por última vaga, duplicidade de paciente,
rollback, deadline, reposição e proteção contra SQL direto. O simulador emite JSONL
com preenchimento, compatibilidade média, pendências, matches urgentes, duração e
vagas evitavelmente vazias comparadas ao máximo possível por área.

## Validação local desta implementação

SAM validate e build no runtime Python 3.13 passaram. Artefato descompactado: 59,3 MiB,
sem módulos do chatbot. Imports e uma simulação de 500 pacientes passaram em container
com limite de 128 MiB, pico de RSS de 57,7 MiB. Isso não mede cold start nem consumo
com conexões reais na AWS. Em 100 populações de 50 profissionais e 500 pacientes,
o simulador não encontrou vagas evitavelmente vazias; p95 local de aproximadamente
14,4 ms por população (somente algoritmo, sem banco).
