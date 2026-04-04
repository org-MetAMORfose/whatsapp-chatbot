# Documentação simplificada do projeto

## 1) O que é este projeto

Este projeto é um **chatbot multi-canal** (Telegram e WhatsApp) com processamento assíncrono.

Em linguagem simples:

- o usuário manda mensagem no canal;
- a mensagem entra no sistema;
- a mensagem é salva no histórico;
- vai para uma fila no Redis;
- o agente processa;
- a resposta volta por outra fila;
- o sistema envia a resposta para o canal certo.

Hoje ele está em fase de base/estrutura, com partes importantes já funcionando e outras ainda em construção.

---

## 2) Arquitetura geral (visão rápida)

### Fluxo principal

1. **Entrada da mensagem**
	 - Telegram (polling)
	 - WhatsApp (webhook)
2. **`MessageReceiverService`** recebe e valida dados mínimos.
3. Mensagem é salva no Redis (histórico por conversa).
4. Mensagem vai para fila **inbound**.
5. **`AgentWorker`** consome fila inbound e gera resposta.
6. Resposta vai para fila **outbound**.
7. **`MessageDispatcherService`** pega da fila outbound.
8. Adaptador do canal envia resposta (Telegram ou WhatsApp).

---

## 3) Estrutura de pastas (explicação simples)

- `app/__main__.py`
	- ponto de entrada da aplicação.
	- sobe Redis, workers, runners e trata desligamento.

- `app/config/`
	- configurações por variável de ambiente.
	- configuração de logs.

- `app/context.py`
	- contexto global de execução.
	- controla shutdown gracioso (`SIGINT`/`SIGTERM`).

- `app/domain/`
	- modelos de domínio: `Message`, `ChatContext`, `Channel`.

- `app/repository/redis_repository.py`
	- leitura/escrita do contexto da conversa no Redis.

- `app/message_queue/`
	- camada de fila com Redis (LPUSH/BRPOP).
	- filas usadas: inbound e outbound.

- `app/services/`
	- `receiver_service.py`: entrada e persistência inicial.
	- `dispatcher_service.py`: envio da resposta ao adaptador correto.

- `app/agent/agent.py`
	- worker que consome a fila inbound e publica na outbound.
	- local da lógica de IA/negócio (ainda simplificada).

- `app/channel_adapters/`
	- integração concreta com Telegram e WhatsApp.

- `app/runners/`
	- orquestram cada canal:
		- Telegram runner (listener + dispatcher)
		- WhatsApp runner (FastAPI + dispatcher)

- `app/controllers/`
	- rotas HTTP (health e webhook WhatsApp).

- `tests/`
	- testes automatizados (atualmente foco em health check).

- `docker-compose.yml` e `Dockerfile`
	- execução com containers.

---

## 4) Funcionalidades que já existem

### Infra e execução

- Inicialização central da aplicação.
- Conexão com Redis.
- Shutdown gracioso.
- Logging em console e arquivo (`logs/chatbot.log`).

### Canais

- **Telegram**
	- recebe mensagens de texto.
	- envia respostas para chat.

- **WhatsApp**
	- valida webhook (`GET`).
	- recebe webhook (`POST`) e extrai mensagens (texto, imagem, documento).
	- envia texto pela API Graph.

### Mensageria e estado

- Fila inbound/outbound no Redis.
- Histórico de conversa por `thread_id` (normalmente `chat_id`).
- Dispatcher por canal.

### Qualidade básica

- teste de health endpoint.
- configuração de ruff/mypy/pytest no projeto.

---

## 5) O que ainda falta desenvolver (pontos pendentes)

## 5.1 Núcleo do agente (prioridade alta)

- Substituir resposta placeholder (`"Processed: ..."`) por lógica real.
- Implementar chamada de LLM/regra de negócio real.
- Tratar contexto de conversa no processamento (estado, memória útil, etc.).

## 5.2 Segurança e robustez (prioridade alta)

- Validar assinatura do webhook do WhatsApp (segurança do endpoint).
- Estratégia de retry/erro para mensagens que falharem.
- Dead-letter queue (DLQ) para mensagens problemáticas.

## 5.3 Consistência de entrada/saída (prioridade média)

- Padronizar tratamento de tipos de mídia (imagem/documento).
- Confirmar idempotência para evitar mensagens duplicadas.
- Melhorar contrato de mensagens da fila (metadados, rastreio, versão).

## 5.4 API e observabilidade (prioridade média)

- Expor health/checks no app realmente executado em produção.
- Adicionar métricas (latência, tamanho das filas, taxa de erro).
- Adicionar tracing/correlation id por mensagem.

## 5.5 Testes (prioridade alta)

- Testes unitários para `receiver_service`, `dispatcher_service`, `agent`.
- Testes de integração com Redis.
- Testes de webhook WhatsApp (payload realista e cenários de erro).
- Testes de contrato por canal.

## 5.6 Alinhamento de documentação e operação (prioridade média)

- Atualizar README para refletir entrada atual da aplicação.
- Documentar claramente variáveis obrigatórias por ambiente.
- Consolidar guia de execução local, Docker e deploy.

---

## 6) Resumo executivo

O projeto já tem uma **boa base de arquitetura** (canais, filas, contexto e dispatch), mas o **coração funcional do bot** (inteligência de resposta e robustez operacional) ainda precisa ser concluído.

Em outras palavras:

- **estrutura pronta:** sim;
- **pipeline principal funcionando:** sim;
- **bot inteligente pronto para produção:** ainda não.

