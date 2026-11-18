# Acolhimento Imediato

Atendimento pago por Pix, oferecido aos psicólogos disponíveis e atendido por vídeo em até 5 minutos, todo pelo WhatsApp.

## Como funciona

1. O paciente escolhe **Atendimento imediato** no chatbot, passa pela triagem (duas perguntas de segurança e a pergunta de idade: menor de 18 anos cai em `imediato_menor`, sem cobrança), aceita os termos, vê os preços (ação `immediate_prices`, valores das variáveis) e escolhe a duração (30 ou 50 minutos).
2. A ação `immediate_create_request` cria o pedido (`immediate_request`, status `awaiting_payment`) e a cobrança Pix; o paciente recebe o código copia e cola. Antes de cobrar ela confere se o imediato está aberto (chave `IMMEDIATE_CARE_ENABLED` e configuração completa, ver abaixo), se já existe um pedido em aberto (um Pix não pago volta a ser mostrado; um pedido pago leva a "em andamento") e se há psicólogo disponível. Se o banco falhar ao criar a cobrança, o paciente cai em `imediato_falha_pix` e nada fica aberto. Se o Pix não for pago em `IMMEDIATE_PAYMENT_TIMEOUT_SECONDS`, o pedido é cancelado (`immediate.payment_timeout.v1`, que consulta o banco antes). `CANCELAR` antes de pagar cancela o pedido e agenda a remoção da cobrança no BB pelo worker (`immediate.cancel_charge.v1`), nunca dentro da transação da mensagem.
3. O Banco do Brasil chama `POST /pix/webhook/{PIX_WEBHOOK_TOKEN}` (ou `.../pix`). O token sozinho não basta: o evento precisa citar um txid conhecido com o valor certo e, com `PIX_PROVIDER=bb`, a cobrança é lida de volta no banco antes de valer. O pedido vai para `queued` e dois itens entram na outbox: `immediate.offer.v1` (agora) e `immediate.timeout.v1` (em `IMMEDIATE_OFFER_TIMEOUT_SECONDS` contados de quando o pagamento chegou, não do horário do banco, para um webhook atrasado ainda ter sua janela). O token é mascarado no access log do uvicorn.
4. O relay (`app/services/immediate_care_relay.py`, dentro do `app-worker`) manda o modelo `acolhimento_solicitacao` para cada psicólogo liberado e com `available_for_immediate = true` (nunca para o próprio paciente), avisa o paciente e o move para o nó `imediato_na_fila`. A oferta mostra só o primeiro nome do paciente.
5. O primeiro psicólogo que toca **Aceitar** fica com o atendimento (`UPDATE ... WHERE status = 'queued'`). O relay cria a sala no Daily (`immediate.accepted.v1`) e manda a cada um o seu link. A sala é **privada**: o endereço puro (`room_url`, o que o painel mostra) não deixa ninguém entrar; cada link enviado leva um token do Daily só daquela pessoa (`patient_room_url`, `professional_room_url`), válido até a sala expirar. Gravação e transcrição nunca são ligadas pelo código; confira no painel do Daily que o domínio também não grava. O paciente continua no nó `imediato_na_fila`: qualquer mensagem devolve o link de novo e a conversa fecha em `imediato_encerrado`. Um pedido aceito bloqueia um novo pedido só até `accepted_at + duração + IMMEDIATE_ROOM_GRACE_MINUTES`.
6. Se ninguém aceita no prazo, o pedido expira, o estorno é feito pela API Pix (`immediate.refund.v1`) e o paciente é avisado. O estorno nunca roda duas vezes (`refunded_at`).

Comandos do psicólogo no WhatsApp: `DISPONÍVEL`, `INDISPONÍVEL`, `Aceitar` (botão do modelo). Com o imediato fechado, nenhum deles é interceptado (seguem para o fluxo). `Aceitar` só é tratado quando uma oferta foi enviada para aquele número; caso contrário segue para o fluxo.

**Quem pode atender:** só psicólogos (área Psicoterapia no perfil de matching ou no campo `area`, com aliases) **liberados pela equipe** no painel (`professional.immediate_approved_at`, gravado só pelo endpoint com chave de API). O `register_type` não serve de critério: o `POST /professionals` público aceita esse campo no corpo. A liberação é o momento de conferir o CRP do profissional. Tirar a liberação também desliga a disponibilidade. Sem nenhum psicólogo disponível, o paciente é avisado antes de qualquer cobrança.

Estorno: o pedido só é marcado como estornado (e o paciente avisado) quando o banco responde `DEVOLVIDO`; enquanto estiver `EM_PROCESSAMENTO` o worker consulta a devolução a cada minuto por até uma hora (o painel mostra "Estorno pendente"). `NAO_REALIZADO` ou prazo esgotado gravam `refund_failed_at`, o painel mostra "Estorno falhou" com "Devolver manualmente" e o paciente é avisado de que a devolução será feita à mão. Se o `PUT` da devolução falhar, o worker consulta a devolução (`GET`) antes de tentar de novo, para nunca pedir duas. O prazo do Pix consulta o banco antes de cancelar e só avisa o paciente quando foi ele mesmo que cancelou; um `CANCELAR` do paciente não gera aviso de "Pix expirou" depois.

Os textos das mensagens do paciente ficam no fluxo do banco e podem ser editados no painel (nós `paciente_imediato`, `imediato_*`). **O link dos termos (`imediato_termos`) aponta para www.orgmetamorfose.com.br/termos, que hoje é o contrato dos planos dos profissionais: antes de ligar, publique os termos do paciente (texto do advogado) e troque o link no editor.**

**Segurança:** com `WHATSAPP_APP_SECRET` preenchido, todo webhook do WhatsApp precisa da assinatura `X-Hub-Signature-256` da Meta (sem ela, qualquer um forjaria um "Aceitar" em nome de um psicólogo). O log do dispatcher registra só o id e o canal das mensagens enviadas, nunca o conteúdo (respostas de triagem, código Pix, links de sala). Erros do BB são registrados sem a URL (que leva a `gw-dev-app-key`). A cobrança não usa `solicitacaoPagador`, para o extrato de quem paga não dizer que é atendimento psicológico. Os textos do relay e do interceptador ficam em `app/services/immediate_care_relay.py` e `app/services/immediate_care_interceptor.py`.

## Variáveis de ambiente

| Variável | Uso |
| --- | --- |
| `IMMEDIATE_CARE_ENABLED` | `false` por padrão: o botão "Atendimento imediato" responde que o serviço ainda não está disponível. Com a chave ligada, o imediato só **abre** se a configuração estiver completa (`PIX_PROVIDER=bb` com todas as `BB_PIX_*`, `PIX_WEBHOOK_TOKEN`, `DAILY_API_KEY`, `WHATSAPP_APP_SECRET`, `WHATSAPP_GRAPH_URL` padrão e uma `CHATBOT_API_KEY` que nunca foi publicada: a atual está no `.env.example` do Front-adm no GitHub e protege o endpoint que libera psicólogos). Se faltar algo, a API e o worker sobem normalmente, o imediato continua fechado e o log mostra em nível CRITICAL o que falta (`app/services/immediate_care_config.py`). |
| `IMMEDIATE_ALLOW_FAKE` | Só em testes locais: `true` deixa ligar o atendimento com Pix e sala simulados, sem assinatura da Meta e com `WHATSAPP_GRAPH_URL` apontando para um servidor falso. Em produção fica `false` (padrão). |
| `WHATSAPP_APP_SECRET` | App Secret do app da Meta (Configurações do app > Básico). Confere a assinatura de cada webhook. Vazio = sem conferência (como hoje), e o imediato não abre. |
| `PIX_PROVIDER` | `fake` (desenvolvimento) ou `bb` (produção). |
| `BB_PIX_CLIENT_ID`, `BB_PIX_CLIENT_SECRET`, `BB_PIX_DEV_APP_KEY` | Credenciais do aplicativo no portal do desenvolvedor do BB. |
| `BB_PIX_CERT_PATH`, `BB_PIX_KEY_PATH` | Certificado e chave privada (mTLS). No servidor: `secrets/bb-pix.crt` e `secrets/bb-pix.key`, montados em `/app/secrets` pelo `docker-compose.yml`. Nunca vão para o git. |
| `BB_PIX_CHAVE` | Chave Pix da conta que recebe. |
| `BB_PIX_BASE_URL`, `BB_PIX_OAUTH_URL` | Homologação: `https://api-pix.hm.bb.com.br/pix/v2` (exige o certificado, mTLS) ou `https://api.hm.bb.com.br/pix/v2` (sem certificado), com `https://oauth.hm.bb.com.br/oauth/token`. Produção: `https://api-pix.bb.com.br/pix/v2` e `https://oauth.bb.com.br/oauth/token`. Testado em 16/11/2026 com as credenciais de teste do aplicativo 286215: token, cobrança, consulta e remoção funcionam em `api.hm.bb.com.br` com a chave de testes do BB `9e881f18-cc66-4fc7-8f2c-a795dbb2bfc1` (a chave da conta real não existe em homologação). O portal confirma que a App Key vai no parâmetro `gw-dev-app-key` também em produção. |
| `PIX_WEBHOOK_TOKEN` | Segredo longo e aleatório que fica na URL do webhook. |
| `PUBLIC_BASE_URL` | URL pública da API (ex.: `https://chatbot.orgmetamorfose.com.br`), usada para registrar o webhook. |
| `IMMEDIATE_PRICES` | Durações e preços, `minutos:centavos` separados por vírgula, na ordem em que o paciente vê. Padrão `10:3000,20:5000,40:10000,60:15000` (10 min R$ 30, 20 min R$ 50, 40 min R$ 100, 60 min R$ 150). Mudar um preço é só trocar a variável e publicar. Uma duração nova precisa também do botão no nó `imediato_duracao` (editor de fluxo); um botão sem preço não cobra nada e leva ao aviso de falha do Pix, com erro no log. Formato inválido mantém o imediato fechado (CRITICAL no log). Com mais de 3 opções o WhatsApp mostra a lista "Ver opções". |
| `IMMEDIATE_OFFER_TIMEOUT_SECONDS` | Prazo para um psicólogo aceitar (padrão 300). |
| `IMMEDIATE_PAYMENT_TIMEOUT_SECONDS` | Prazo para pagar o Pix (padrão 1800). |
| `IMMEDIATE_ROOM_GRACE_MINUTES` | Minutos extras de validade da sala além da duração (padrão 15). |
| `DAILY_API_KEY` | Chave da API do Daily. Vazia = sala simulada (`https://exemplo.daily.co/...`), e o imediato só abre com `IMMEDIATE_ALLOW_FAKE=true`. |

## Colocando em produção

1. **Meta (WhatsApp Manager):** ✅ feito em 18/11/2026. Modelo `acolhimento_solicitacao`, idioma `pt_BR`, aprovado como *Utility* na conta MetAMORfose (WABA 1333567748597616), com um botão de resposta rápida **Aceitar**. Corpo:

   > Você está como DISPONÍVEL no acolhimento imediato e chegou uma solicitação: {{1}}, sessão de {{2}} minutos, R$ {{3}}. Para atender, toque em Aceitar em até 5 minutos; quem aceitar primeiro fica com o atendimento. Para parar de receber, envie INDISPONÍVEL.

   A primeira versão (`acolhimento_oferta`, "Novo acolhimento imediato: ...") foi reclassificada pela Meta como *Marketing*, que custa mais por mensagem e pode ser retida pelo WhatsApp; não é usada. Um modelo novo precisa ficar ligado ao status DISPONÍVEL do profissional para continuar *Utility*.

   Exemplos para a aprovação: `Maria`, `20`, `50,00`.
2. **Banco do Brasil:** criar o aplicativo com a API Pix, baixar o certificado, colocar `bb-pix.crt` e `bb-pix.key` em `secrets/` no servidor e preencher as variáveis `BB_PIX_*`. Começar em homologação.
3. **Daily:** criar a conta no e-mail da MetAMORfose e gerar a chave da API.
4. **GitHub:** cadastrar os segredos (`BB_PIX_CLIENT_ID`, `BB_PIX_CLIENT_SECRET`, `BB_PIX_DEV_APP_KEY`, `BB_PIX_CHAVE`, `PIX_WEBHOOK_TOKEN`, `DAILY_API_KEY`, `WHATSAPP_APP_SECRET`) e as variáveis (`PIX_PROVIDER=bb`, `BB_PIX_BASE_URL`, `BB_PIX_OAUTH_URL`, `PUBLIC_BASE_URL`, preços e prazos). `IMMEDIATE_CARE_ENABLED` só vira `true` no passo 8. O deploy escreve tudo no `.env` do servidor.
5. **Deploy, primeiro o chatbot e depois o painel:** a migração `0018` cria a tabela e as colunas; a `0019` publica os nós do fluxo. O worker recarrega o fluxo ao subir. Com `IMMEDIATE_CARE_ENABLED=false` (padrão) nada muda para o paciente além da mensagem "ainda não está disponível". O painel lê as colunas novas de `professional` pelo Prisma, então **o PR do Front-adm só pode ser mergeado depois que o deploy do chatbot (com a `0018`) terminar verde**.
   - **A `0019` confere o fluxo de produção antes de escrever:** o nó `paciente_imediato` precisa ser ainda o fim com "[URL em construção]", sem saídas; a transição "Atendimento imediato" de `paciente_tipo_atendimento` precisa levar a ele; nenhum nó com os nomes novos pode existir. Se algo não bater, ela para com a lista das diferenças e **não altera nada**. O deploy roda as migrações **antes** de parar a API e o worker, então o bot continua no ar com a versão anterior; desfaça a edição no editor (ou ajuste a migração) e rode o deploy de novo.
   - A `0019` publica uma revisão nova do fluxo (versão + 1): os workers recarregam e rascunhos abertos antes do deploy aparecem como desatualizados no editor (recrie o rascunho).
   - Desfazer a `0018` é recusado enquanto `immediate_request` tiver pedidos (registros de pagamento e estorno).
   - **Webhook em HTTPS:** o BB só chama URLs públicas em HTTPS. `PUBLIC_BASE_URL` precisa apontar para um domínio com certificado válido encaminhando `/pix/webhook/*` para a API (porta 8000 do compose); o portal do BB (aplicativo > Certificados) confirma que o webhook usa mTLS: o BB apresenta um certificado de cliente, então o proxy na frente da API precisa pedir esse certificado e confiar na cadeia do BB (botão "Baixar certificado BB" na mesma tela), servindo HTTPS com certificado válido de uma autoridade confiável. Não é mais preciso enviar o certificado do servidor ao BB.
6. **Webhook do BB:** com a API no ar, rodar uma vez:

   ```bash
   docker compose run --rm --no-deps api python -m app.scripts.registrar_webhook_pix
   ```

   O script registra `{PUBLIC_BASE_URL}/pix/webhook/{PIX_WEBHOOK_TOKEN}` para a chave `BB_PIX_CHAVE`.
7. **Teste real em homologação:** liberar um psicólogo no painel; ele manda `DISPONÍVEL`; um paciente pede o atendimento e paga; conferir a oferta, o aceite, a sala e, num segundo teste sem ninguém disponível, o estorno. Conferir também o fuso do campo `horario`/`calendario.criacao` que o BB devolve.
8. **Antes de ligar:** gerar uma `CHATBOT_API_KEY` nova (a atual foi publicada no GitHub) e trocar nos dois deploys, senha no painel (variáveis `ADMIN_USER`/`ADMIN_PASSWORD` do Front-adm: o painel mostra quem pediu acolhimento e libera psicólogos), termos do paciente publicados e link trocado em `imediato_termos`, combinado de repasse aos psicólogos, psicólogos liberados no painel depois de conferir o CRP.
9. **Ligar:** `IMMEDIATE_CARE_ENABLED=true` nas variáveis do GitHub e novo deploy. Conferir no log que aparece "Acolhimento imediato aberto" e não um CRITICAL. Os textos dizem "5 minutos"; se `IMMEDIATE_OFFER_TIMEOUT_SECONDS` mudar, ajuste os textos dos nós no editor de fluxo e o modelo da Meta.

## Desenvolvimento local

Com `PIX_PROVIDER=fake` (e, para ligar a chave, `IMMEDIATE_ALLOW_FAKE=true`), o código Pix é `PIX-SIMULADO-<txid>` e o pagamento é simulado postando o webhook. `PIX_WEBHOOK_TOKEN` precisa estar preenchido no `.env` local, senão o webhook responde 404:

```bash
curl -X POST "http://localhost:8000/pix/webhook/$PIX_WEBHOOK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"pix":[{"txid":"<txid do pedido>","endToEndId":"E00000000202611122000000000000001","valor":"60.00","horario":"2026-11-12T20:00:00Z"}]}'
```

O txid aparece na tabela `immediate_request`. Sem `DAILY_API_KEY`, a sala é um link simulado. Para testar com a chave ligada localmente, use `IMMEDIATE_ALLOW_FAKE=true`.

## Painel

A página `/imediato` do Front-adm lê a tabela `immediate_request` direto pelo Prisma (status, valor, horários, psicólogo, se a sala foi criada, estorno, estorno falhou). Os links da sala com token nunca aparecem no painel. Na página do profissional, "Liberar para imediato" e "Disponível para imediato" chamam os endpoints abaixo pelo servidor do painel (chave `X-Chatbot-Api-Key`). Nenhum endpoint da API devolve dados de pacientes.

- `PATCH /immediate/professionals/{id}/approval` com `{"approved": true|false}` libera ou tira a liberação (tirar também desliga a disponibilidade).
- `PATCH /immediate/professionals/{id}/availability` com `{"available": true|false}` liga (só psicólogo liberado) ou desliga a disponibilidade.
