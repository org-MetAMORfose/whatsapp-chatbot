# Acolhimento Imediato

Atendimento pago por Pix, oferecido aos psicólogos disponíveis e atendido por vídeo em até 5 minutos, todo pelo WhatsApp.

## Como funciona

1. O paciente escolhe **Atendimento imediato** no chatbot, passa pela triagem (duas perguntas de segurança), aceita os termos e escolhe a duração (30 ou 50 minutos).
2. A ação `immediate_create_request` cria o pedido (`immediate_request`, status `awaiting_payment`) e a cobrança Pix; o paciente recebe o código copia e cola. Antes de cobrar ela confere a chave `IMMEDIATE_CARE_ENABLED`, se já existe um pedido em aberto (um Pix não pago volta a ser mostrado; um pedido pago leva a "em andamento") e se há psicólogo disponível. Se o banco falhar ao criar a cobrança, o paciente cai em `imediato_falha_pix` e nada fica aberto. Se o Pix não for pago em `IMMEDIATE_PAYMENT_TIMEOUT_SECONDS`, o pedido é cancelado (`immediate.payment_timeout.v1`, que consulta o banco antes). `CANCELAR` antes de pagar cancela o pedido e agenda a remoção da cobrança no BB pelo worker (`immediate.cancel_charge.v1`), nunca dentro da transação da mensagem.
3. O Banco do Brasil chama `POST /pix/webhook/{PIX_WEBHOOK_TOKEN}` (ou `.../pix`). O token sozinho não basta: o evento precisa citar um txid conhecido com o valor certo e, com `PIX_PROVIDER=bb`, a cobrança é lida de volta no banco antes de valer. O pedido vai para `queued` e dois itens entram na outbox: `immediate.offer.v1` (agora) e `immediate.timeout.v1` (em `IMMEDIATE_OFFER_TIMEOUT_SECONDS` contados de quando o pagamento chegou, não do horário do banco, para um webhook atrasado ainda ter sua janela). O token é mascarado no access log do uvicorn.
4. O relay (`app/services/immediate_care_relay.py`, dentro do `app-worker`) manda o modelo `acolhimento_oferta` para cada psicólogo com `available_for_immediate = true`, avisa o paciente e o move para o nó `imediato_na_fila`.
5. O primeiro psicólogo que toca **Aceitar** fica com o atendimento (`UPDATE ... WHERE status = 'queued'`). O relay cria a sala no Daily (`immediate.accepted.v1`) e manda o link para os dois. O paciente continua no nó `imediato_na_fila`: qualquer mensagem devolve o link de novo e a conversa fecha em `imediato_encerrado`. Um pedido aceito bloqueia um novo pedido só até `accepted_at + duração + IMMEDIATE_ROOM_GRACE_MINUTES`.
6. Se ninguém aceita no prazo, o pedido expira, o estorno é feito pela API Pix (`immediate.refund.v1`) e o paciente é avisado. O estorno nunca roda duas vezes (`refunded_at`).

Comandos do psicólogo no WhatsApp: `DISPONÍVEL`, `INDISPONÍVEL`, `Aceitar` (botão do modelo). Só psicólogos com cadastro aprovado (não `PENDING_REVIEW`) e área Psicoterapia (perfil de matching ou campo `area`, com aliases). Sem nenhum psicólogo disponível, o paciente é avisado antes de qualquer cobrança.

Estorno: o pedido só é marcado como estornado (e o paciente avisado) quando o banco responde `DEVOLVIDO`; enquanto estiver `EM_PROCESSAMENTO` o worker consulta a devolução a cada minuto por até uma hora (o painel mostra "Estorno pendente"). `NAO_REALIZADO` ou prazo esgotado gravam `refund_failed_at`, o painel mostra "Estorno falhou" com "Devolver manualmente" e o paciente é avisado de que a devolução será feita à mão. Se o `PUT` da devolução falhar, o worker consulta a devolução (`GET`) antes de tentar de novo, para nunca pedir duas. O prazo do Pix consulta o banco antes de cancelar e só avisa o paciente quando foi ele mesmo que cancelou; um `CANCELAR` do paciente não gera aviso de "Pix expirou" depois.

Os textos das mensagens do paciente ficam no fluxo do banco e podem ser editados no painel (nós `paciente_imediato`, `imediato_*`). Os textos do relay e do interceptador ficam em `app/services/immediate_care_relay.py` e `app/services/immediate_care_interceptor.py`.

## Variáveis de ambiente

| Variável | Uso |
| --- | --- |
| `IMMEDIATE_CARE_ENABLED` | `false` por padrão: o botão "Atendimento imediato" responde que o serviço ainda não está disponível. Ligue só com o Pix do BB e o modelo da Meta prontos. Com a chave ligada, a API e o worker **recusam subir** com `PIX_PROVIDER=fake` ou sem `DAILY_API_KEY`. |
| `IMMEDIATE_ALLOW_FAKE` | Só em testes locais: `true` deixa ligar o atendimento com Pix e sala simulados. Em produção fica `false` (padrão). |
| `PIX_PROVIDER` | `fake` (desenvolvimento) ou `bb` (produção). |
| `BB_PIX_CLIENT_ID`, `BB_PIX_CLIENT_SECRET`, `BB_PIX_DEV_APP_KEY` | Credenciais do aplicativo no portal do desenvolvedor do BB. |
| `BB_PIX_CERT_PATH`, `BB_PIX_KEY_PATH` | Certificado e chave privada (mTLS). No servidor: `secrets/bb-pix.crt` e `secrets/bb-pix.key`, montados em `/app/secrets` pelo `docker-compose.yml`. Nunca vão para o git. |
| `BB_PIX_CHAVE` | Chave Pix da conta que recebe. |
| `BB_PIX_BASE_URL`, `BB_PIX_OAUTH_URL` | Homologação: `https://api-pix.hm.bb.com.br/pix/v2` e `https://oauth.hm.bb.com.br/oauth/token`. Produção: `https://api-pix.bb.com.br/pix/v2` e `https://oauth.bb.com.br/oauth/token`. Confirmar no portal do BB. |
| `PIX_WEBHOOK_TOKEN` | Segredo longo e aleatório que fica na URL do webhook. |
| `PUBLIC_BASE_URL` | URL pública da API (ex.: `https://chatbot.orgmetamorfose.com.br`), usada para registrar o webhook. |
| `IMMEDIATE_PRICE_30_CENTS`, `IMMEDIATE_PRICE_50_CENTS` | Preços em centavos (padrão 6000 e 9000). |
| `IMMEDIATE_OFFER_TIMEOUT_SECONDS` | Prazo para um psicólogo aceitar (padrão 300). |
| `IMMEDIATE_PAYMENT_TIMEOUT_SECONDS` | Prazo para pagar o Pix (padrão 1800). |
| `IMMEDIATE_ROOM_GRACE_MINUTES` | Minutos extras de validade da sala além da duração (padrão 15). |
| `DAILY_API_KEY` | Chave da API do Daily. Vazia = sala simulada (`https://exemplo.daily.co/...`), permitida só com `IMMEDIATE_ALLOW_FAKE=true`. |

## Colocando em produção

1. **Meta (WhatsApp Manager):** criar e aprovar o modelo `acolhimento_oferta`, idioma `pt_BR`, categoria *Utility*, com um botão de resposta rápida **Aceitar**. Corpo:

   > Novo acolhimento imediato: {{1}} precisa de uma sessão de {{2}} minutos agora (R$ {{3}}). Toque em Aceitar nos próximos 5 minutos para ficar com o atendimento.

   Exemplos para a aprovação: `Maria`, `30`, `60,00`.
2. **Banco do Brasil:** criar o aplicativo com a API Pix, baixar o certificado, colocar `bb-pix.crt` e `bb-pix.key` em `secrets/` no servidor e preencher as variáveis `BB_PIX_*`. Começar em homologação.
3. **Daily:** criar a conta no e-mail da MetAMORfose e gerar a chave da API.
4. **GitHub:** cadastrar os segredos (`BB_PIX_CLIENT_ID`, `BB_PIX_CLIENT_SECRET`, `BB_PIX_DEV_APP_KEY`, `BB_PIX_CHAVE`, `PIX_WEBHOOK_TOKEN`, `DAILY_API_KEY`) e as variáveis (`PIX_PROVIDER=bb`, `BB_PIX_BASE_URL`, `BB_PIX_OAUTH_URL`, `PUBLIC_BASE_URL`, preços e prazos). `IMMEDIATE_CARE_ENABLED` só vira `true` no passo 8. O deploy escreve tudo no `.env` do servidor.
5. **Deploy, primeiro o chatbot e depois o painel:** a migração `0018` cria a tabela e as colunas; a `0019` publica os nós do fluxo. O worker recarrega o fluxo ao subir. Com `IMMEDIATE_CARE_ENABLED=false` (padrão) nada muda para o paciente além da mensagem "ainda não está disponível". O painel lê as colunas novas de `professional` pelo Prisma, então o CD do Front-adm só pode rodar depois que o deploy do chatbot (com a `0018`) terminar. Antes do merge, conferir no editor de fluxo que a `0019` encontra o que espera: o nó `paciente_imediato` e a transição "Atendimento imediato" em `paciente_tipo_atendimento`, e nenhum nó `imediato_*` criado à mão (a migração aborta se faltar algo, e o deploy para api e worker antes de migrar).
   - **Webhook em HTTPS:** o BB só chama URLs públicas em HTTPS. `PUBLIC_BASE_URL` precisa apontar para um domínio com certificado válido encaminhando `/pix/webhook/*` para a API (porta 8000 do compose); confirmar no portal do BB se o webhook exige mTLS do lado do servidor.
6. **Webhook do BB:** com a API no ar, rodar uma vez:

   ```bash
   docker compose run --rm --no-deps api python -m app.scripts.registrar_webhook_pix
   ```

   O script registra `{PUBLIC_BASE_URL}/pix/webhook/{PIX_WEBHOOK_TOKEN}` para a chave `BB_PIX_CHAVE`.
7. **Teste real em homologação:** um psicólogo manda `DISPONÍVEL`; um paciente pede o atendimento e paga; conferir a oferta, o aceite, a sala e, num segundo teste sem ninguém disponível, o estorno. Conferir também o fuso do campo `horario`/`calendario.criacao` que o BB devolve.
8. **Ligar:** `IMMEDIATE_CARE_ENABLED=true` nas variáveis do GitHub e novo deploy. Os textos dizem "5 minutos"; se `IMMEDIATE_OFFER_TIMEOUT_SECONDS` mudar, ajuste os textos dos nós no editor de fluxo e o modelo da Meta.

## Desenvolvimento local

Com `PIX_PROVIDER=fake` (e, para ligar a chave, `IMMEDIATE_ALLOW_FAKE=true`), o código Pix é `PIX-SIMULADO-<txid>` e o pagamento é simulado postando o webhook. `PIX_WEBHOOK_TOKEN` precisa estar preenchido no `.env` local, senão o webhook responde 404:

```bash
curl -X POST "http://localhost:8000/pix/webhook/$PIX_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pix":[{"txid":"<txid do pedido>","endToEndId":"E00000000202611122000000000000001","valor":"60.00","horario":"2026-11-12T20:00:00Z"}]}'
```

O txid aparece na tabela `immediate_request` (ou em `GET /immediate/requests` com o cabeçalho `X-Chatbot-Api-Key`). Sem `DAILY_API_KEY`, a sala é um link simulado.

## Painel

A página `/imediato` do Front-adm lê a tabela `immediate_request` direto pelo Prisma (status, valor, horários, psicólogo, sala, estorno, estorno falhou) e o botão "Disponível para imediato" na página do profissional chama o endpoint abaixo pelo servidor do painel. Endpoints da API (chave `X-Chatbot-Api-Key`):

- `GET /immediate/requests?limit=100` lista os pedidos (chave de API).
- `PATCH /immediate/professionals/{id}/availability` com `{"available": true|false}` liga ou desliga a disponibilidade (chave de API).
