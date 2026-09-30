# ruff: noqa: E501
"""Seed every chatbot node, transition, button and action from the former TOML flow."""

import json
import unicodedata

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_seed_flow"
down_revision = "0011_chatbot_flow"
branch_labels = None
depends_on = None

SCHEMA = "chatbot_flow"
OPTIONAL_ACTIONS = {"sheets_register_patient", "sheets_register_professional"}
INPUT_ERRORS = {
    "TEXT": "Envie uma resposta em texto.",
    "EMAIL": "Envie um e-mail válido. Exemplo: nome@dominio.com.br.",
    "DATE": "Envie uma data válida no formato DD/MM/AAAA.",
    "NUMBER": "Envie um número válido.",
    "IMAGE": "Envie uma imagem.",
    "DOCUMENT": "Envie um documento.",
    "VIDEO": "Envie um vídeo.",
    "AUTO": "Não foi possível processar sua resposta. Tente novamente.",
}
FLOW_DATA = json.loads(r"""
{
  "nodes": {
    "start": {
      "description": "Mensagem inicial e seleção do tipo de atendimento.",
      "message": "Olá, tudo bem?\n\nComo posso ajudar você hoje?\nSelecione a opção desejada\n\nCaso tenha preenchido alguma informação incorretamente ou queira recomeçar o atendimento, basta enviar a palavra RESET a qualquer momento para reiniciar o fluxo.\n",
      "buttons": [
        "Quero ser paciente",
        "Sou profissional",
        "Dúvidas"
      ],
      "transitions": [
        {
          "target": "paciente_nome",
          "conditions": [
            "quero ser paciente"
          ]
        },
        {
          "target": "profissional_start",
          "conditions": [
            "sou profissional"
          ]
        },
        {
          "target": "faq_inicio",
          "conditions": [
            "duvidas"
          ]
        }
      ],
      "title": "Início do atendimento"
    },
    "profissional_start": {
      "description": "Entrada específica para profissionais.",
      "message": "Você já faz parte da Rede MetAMORfose ou deseja participar do processo seletivo?",
      "buttons": [
        "Processo seletivo",
        "Já sou da Rede",
        "Dúvidas"
      ],
      "transitions": [
        {
          "target": "lgpd",
          "conditions": [
            "processo seletivo"
          ]
        },
        {
          "target": "profissional_rede_inicio",
          "conditions": [
            "ja sou da rede"
          ]
        },
        {
          "target": "faq_inicio",
          "conditions": [
            "duvidas"
          ]
        }
      ],
      "title": "Início do atendimento profissional"
    },
    "faq_inicio": {
      "description": "Introdução ao FAQ e recebimento da primeira pergunta.",
      "actions": [
        "faq_process_question"
      ],
      "message": "Olá! Envie sua dúvida sobre a Rede MetAMORfose e eu buscarei uma resposta em nossa base de conhecimento.",
      "input": "Texto",
      "transitions": [
        {
          "target": "faq_resposta",
          "conditions": []
        }
      ],
      "title": "Início do FAQ"
    },
    "faq_resposta": {
      "description": "Resposta do FAQ antes da oferta de atendimento humano.",
      "actions": [
        "faq_continue_or_satisfy"
      ],
      "message": "Você pode enviar outra pergunta diretamente por aqui. Se suas dúvidas já foram esclarecidas, clique em \"Estou satisfeito\" para escolher se quer ser paciente e receber atendimento, ou se quer resolver questões como profissional de saúde.",
      "buttons": [
        "Estou satisfeito"
      ],
      "transitions": [
        {
          "target": "faq_satisfeito",
          "conditions": [
            "estou satisfeito"
          ]
        },
        {
          "target": "faq_resposta",
          "conditions": []
        }
      ],
      "title": "Resposta do FAQ antes da oferta de atendimento humano"
    },
    "faq_resposta_com_atendimento": {
      "description": "Resposta do FAQ com opção adicional de atendimento humano.",
      "actions": [
        "faq_continue_or_finish"
      ],
      "message": "Você pode continuar enviando suas perguntas diretamente por aqui. Se suas dúvidas já foram esclarecidas, clique em \"Estou satisfeito\". Se precisar falar com nossa equipe, clique em \"Falar com atendente\".",
      "buttons": [
        "Estou satisfeito",
        "Falar com atendente"
      ],
      "transitions": [
        {
          "target": "faq_satisfeito",
          "conditions": [
            "estou satisfeito"
          ]
        },
        {
          "target": "faq_escalado",
          "conditions": [
            "falar com atendente"
          ]
        },
        {
          "target": "faq_resposta_com_atendimento",
          "conditions": []
        }
      ],
      "title": "Resposta do FAQ com opção adicional de atendimento humano"
    },
    "faq_satisfeito": {
      "description": "Encerramento do FAQ após confirmação de satisfação.",
      "message": "Que bom que conseguimos ajudar! Quando precisar, é só iniciar uma nova conversa.",
      "end": true,
      "title": "Encerramento do FAQ após confirmação de satisfação"
    },
    "faq_escalado": {
      "description": "Encerramento do FAQ com solicitação de atendimento humano.",
      "message": "Alguém da nossa equipe de suporte entrará em contato em até 24 horas, considerando apenas dias úteis.",
      "end": true,
      "title": "Encerramento do FAQ com solicitação de atendimento humano"
    },
    "feedback_inicio": {
      "description": "Solicitação de feedback.",
      "actions": [
        "postgres_set_feedback_state"
      ],
      "message": "Gostaria de compartilhar algum feedback sobre o atendimento ou sobre a Rede MetAMORfose?",
      "input": "Texto",
      "transitions": [
        {
          "target": "agradecimento",
          "conditions": []
        }
      ],
      "title": "Coleta de feedback"
    },
    "agradecimento": {
      "description": "Agradecimento pelo feedback recebido.",
      "message": "Obrigado pelo seu feedback! Sua opinião é muito importante para nós.",
      "end": true,
      "title": "Agradecimento pelo feedback recebido"
    },
    "paciente_tipo_atendimento": {
      "description": "Escolhe entre atendimento imediato e cadastro normal.",
      "actions": [
        "postgres_route_patient_registration"
      ],
      "message": "Você procura atendimento imediato ou atendimento agendado?",
      "buttons": [
        "Atendimento imediato",
        "Agendar atendimento"
      ],
      "transitions": [
        {
          "target": "paciente_imediato",
          "conditions": [
            "atendimento imediato"
          ]
        },
        {
          "target": "paciente_inicio",
          "conditions": [
            "agendar atendimento"
          ]
        }
      ],
      "title": "Tipo de atendimento do paciente"
    },
    "paciente_imediato": {
      "description": "Encaminhamento externo para atendimento imediato.",
      "message": "Você pode pedir atendimento imediato por este link:\n\n[URL em construção]",
      "end": true,
      "title": "Encaminhamento externo para atendimento imediato"
    },
    "paciente_nome": {
      "description": "Coleta do nome para o primeiro cadastro do paciente.",
      "actions": [
        "redis_update_patient_name",
        "postgres_update_person_name"
      ],
      "message": "Olá, tudo bem? Para começarmos, qual é o seu nome?",
      "input": "Texto",
      "transitions": [
        {
          "target": "paciente_tipo_atendimento",
          "conditions": []
        }
      ],
      "title": "Nome para o primeiro cadastro do paciente"
    },
    "paciente_inicio": {
      "description": "Coleta da área de atendimento desejada.",
      "actions": [
        "redis_update_patient_area"
      ],
      "message": "Prazer em te conhecer! Qual área você deseja receber atendimento?\n\nEstamos aqui para te conectar aos profissionais da nossa Rede MetAMORfose de telemedicina, para acolher tudo o que você estiver sentindo!",
      "buttons": [
        "Psiquiatria",
        "Nutrição",
        "Clínico geral",
        "Psicoterapia"
      ],
      "transitions": [
        {
          "target": "paciente_psico_abordagem",
          "conditions": [
            "psicoterapia"
          ]
        },
        {
          "target": "paciente_data_nascimento",
          "conditions": [
            "psiquiatria",
            "nutricao",
            "clinico geral"
          ]
        }
      ],
      "title": "Área de atendimento do paciente"
    },
    "paciente_psico_abordagem": {
      "description": "Coleta da abordagem desejada para psicoterapia.",
      "actions": [
        "redis_update_patient_psychotherapy_approach"
      ],
      "message": "Você procura alguma abordagem específica para a psicoterapia?",
      "buttons": [
        "TCC",
        "Psicanálise",
        "Sem preferência"
      ],
      "transitions": [
        {
          "target": "paciente_data_nascimento",
          "conditions": [
            "tcc",
            "psicanalise",
            "sem preferencia"
          ]
        }
      ],
      "title": "Abordagem desejada para psicoterapia"
    },
    "paciente_data_nascimento": {
      "description": "Coleta e valida a data de nascimento do paciente.",
      "actions": [
        "redis_update_patient_birth_date"
      ],
      "message": "Qual é a sua data de nascimento? Envie no formato DD/MM/AAAA. Exemplo: 15/08/1990.",
      "input": "Texto",
      "transitions": [
        {
          "target": "paciente_faixa_valor",
          "conditions": []
        }
      ],
      "title": "Data de nascimento do paciente"
    },
    "paciente_psico_perfil": {
      "description": "Coleta de preferência de perfil profissional.",
      "actions": [
        "redis_update_patient_professional_profile"
      ],
      "message": "Você tem alguma preferência sobre o perfil do profissional?",
      "buttons": [
        "LGBTQIAPN+",
        "Mulher",
        "Mulher negra",
        "Homem negro",
        "Sem preferência"
      ],
      "transitions": [
        {
          "target": "paciente_faixa_valor",
          "conditions": [
            "lgbtqiapn+",
            "mulher",
            "mulher negra",
            "homem negro",
            "sem preferencia"
          ]
        }
      ],
      "title": "Preferência de perfil profissional"
    },
    "paciente_faixa_valor": {
      "description": "Coleta da faixa de valor por sessão.",
      "actions": [
        "redis_update_patient_price_range",
        "postgres_register_new_patient_request",
        "sheets_register_patient"
      ],
      "message": "Qual dessas faixas por sessão se encaixa com a sua realidade?\n\nOs valores variam conforme o tempo de experiência clínica, cursos, qualificações, especializações e disponibilidade dos profissionais de saúde.",
      "buttons": [
        "Até R$150",
        "Até R$300",
        "Até R$600"
      ],
      "transitions": [
        {
          "target": "paciente_primeiro_finalizado",
          "conditions": [
            "ate r$150",
            "ate r$300",
            "ate r$600"
          ]
        }
      ],
      "title": "Faixa de valor por sessão"
    },
    "paciente_primeiro_finalizado": {
      "description": "Confirmação do primeiro cadastro normal.",
      "message": "Cadastro inicial concluído.\n\nEm breve um dos nossos profissionais de saúde vai te chamar aqui no WhatsApp.",
      "end": true,
      "title": "Primeiro cadastro normal"
    },
    "paciente_retorno_resumo": {
      "description": "Apresenta o último cadastro e permite mantê-lo ou alterá-lo.",
      "actions": [
        "postgres_register_returning_patient_from_last_request",
        "postgres_route_patient_preference_update"
      ],
      "message": "Você prefere manter ou atualizar as preferências para seu próximo profissional?",
      "buttons": [
        "Manter",
        "Atualizar"
      ],
      "transitions": [
        {
          "target": "paciente_retorno_finalizado",
          "conditions": [
            "manter"
          ]
        },
        {
          "target": "paciente_retorno_campos_geral",
          "conditions": [
            "atualizar"
          ]
        }
      ],
      "title": "Apresenta o último cadastro e permite mantê-lo ou alterá-lo"
    },
    "paciente_retorno_campos_geral": {
      "description": "Escolhe uma preferência aplicável a qualquer área de atendimento.",
      "message": "O que você quer ajustar para o seu próximo profissional?",
      "buttons": [
        "Nome",
        "Área",
        "Perfil profissional",
        "Faixa de valor"
      ],
      "transitions": [
        {
          "target": "paciente_corrigir_nome",
          "conditions": [
            "nome"
          ]
        },
        {
          "target": "paciente_corrigir_area",
          "conditions": [
            "area"
          ]
        },
        {
          "target": "paciente_corrigir_perfil",
          "conditions": [
            "perfil profissional"
          ]
        },
        {
          "target": "paciente_corrigir_faixa_valor",
          "conditions": [
            "faixa de valor"
          ]
        }
      ],
      "title": "Uma preferência aplicável a qualquer área de atendimento"
    },
    "paciente_retorno_campos_psicoterapia": {
      "description": "Escolhe uma preferência aplicável à psicoterapia.",
      "message": "O que você quer ajustar para o seu próximo profissional?",
      "buttons": [
        "Nome",
        "Área",
        "Abordagem",
        "Perfil profissional",
        "Faixa de valor"
      ],
      "transitions": [
        {
          "target": "paciente_corrigir_nome",
          "conditions": [
            "nome"
          ]
        },
        {
          "target": "paciente_corrigir_area",
          "conditions": [
            "area"
          ]
        },
        {
          "target": "paciente_corrigir_abordagem",
          "conditions": [
            "abordagem"
          ]
        },
        {
          "target": "paciente_corrigir_perfil",
          "conditions": [
            "perfil profissional"
          ]
        },
        {
          "target": "paciente_corrigir_faixa_valor",
          "conditions": [
            "faixa de valor"
          ]
        }
      ],
      "title": "Uma preferência aplicável à psicoterapia"
    },
    "paciente_corrigir_nome": {
      "description": "Atualiza o nome no cadastro temporário e no cadastro permanente da pessoa.",
      "actions": [
        "redis_update_patient_name",
        "postgres_update_person_name",
        "redis_get_patient_stage_summary"
      ],
      "message": "Qual é o nome correto?",
      "input": "Texto",
      "transitions": [
        {
          "target": "paciente_retorno_resumo",
          "conditions": []
        }
      ],
      "title": "Correção do nome do paciente"
    },
    "paciente_corrigir_area": {
      "description": "Atualiza a área desejada.",
      "actions": [
        "redis_update_patient_area",
        "redis_get_patient_stage_summary"
      ],
      "message": "Qual área você deseja receber atendimento?",
      "buttons": [
        "Psiquiatria",
        "Nutrição",
        "Clínico geral",
        "Psicoterapia"
      ],
      "transitions": [
        {
          "target": "paciente_retorno_resumo",
          "conditions": [
            "psiquiatria",
            "nutricao",
            "clinico geral",
            "psicoterapia"
          ]
        }
      ],
      "title": "Correção da área de atendimento do paciente"
    },
    "paciente_corrigir_abordagem": {
      "description": "Atualiza a abordagem desejada para psicoterapia.",
      "actions": [
        "redis_update_patient_psychotherapy_approach",
        "redis_get_patient_stage_summary"
      ],
      "message": "Qual abordagem você procura?",
      "buttons": [
        "TCC",
        "Psicanálise",
        "Sem preferência"
      ],
      "transitions": [
        {
          "target": "paciente_retorno_resumo",
          "conditions": [
            "tcc",
            "psicanalise",
            "sem preferencia"
          ]
        }
      ],
      "title": "Correção da abordagem de psicoterapia"
    },
    "paciente_corrigir_perfil": {
      "description": "Atualiza a preferência de perfil profissional.",
      "actions": [
        "redis_update_patient_professional_profile",
        "redis_get_patient_stage_summary"
      ],
      "message": "Qual perfil profissional você prefere?",
      "buttons": [
        "LGBTQIAPN+",
        "Mulher",
        "Mulher negra",
        "Homem negro",
        "Sem preferência"
      ],
      "transitions": [
        {
          "target": "paciente_retorno_resumo",
          "conditions": [
            "lgbtqiapn+",
            "mulher",
            "mulher negra",
            "homem negro",
            "sem preferencia"
          ]
        }
      ],
      "title": "Correção do perfil profissional desejado"
    },
    "paciente_corrigir_faixa_valor": {
      "description": "Atualiza a faixa de valor desejada.",
      "actions": [
        "redis_update_patient_price_range",
        "redis_get_patient_stage_summary"
      ],
      "message": "Qual faixa de valor se encaixa com a sua realidade?",
      "buttons": [
        "Até R$150",
        "Até R$300",
        "Até R$600"
      ],
      "transitions": [
        {
          "target": "paciente_retorno_resumo",
          "conditions": [
            "ate r$150",
            "ate r$300",
            "ate r$600"
          ]
        }
      ],
      "title": "Correção da faixa de valor"
    },
    "paciente_retorno_finalizado": {
      "description": "Confirmação de solicitação normal para paciente retornando.",
      "message": "Recebi suas preferências. A equipe vai revisar e seguir com você por aqui.",
      "end": true,
      "title": "Solicitação normal para paciente retornando"
    },
    "profissional_rede_inicio": {
      "description": "Triagem inicial do profissional já cadastrado.",
      "actions": [
        "postgres_set_professional_support_state"
      ],
      "message": "Olá! Como podemos ajudar você hoje?",
      "buttons": [
        "Outros assuntos",
        "Reposição paciente",
        "Renovação por Pix"
      ],
      "transitions": [
        {
          "target": "falar_atendente",
          "conditions": [
            "outros assuntos"
          ]
        },
        {
          "target": "solicitar_reposicao",
          "conditions": [
            "reposicao paciente"
          ]
        },
        {
          "target": "renovacao_pix",
          "conditions": [
            "renovacao por pix",
            "renovação por pix"
          ]
        }
      ],
      "title": "Triagem inicial do profissional já cadastrado"
    },
    "renovacao_pix": {
      "description": "Reenvio das instruções de renovação por Pix.",
      "actions": [
        "postgres_set_payment_renewal_state"
      ],
      "message": "Para renovar por Pix, faça o pagamento para Luiza Fogaça, gestora da plataforma.\n\nChave Pix: 61609380000150\n\nComo o pagamento via Pix é feito fora do site, o sistema não consegue atualizar o selo de \"ativo\" automaticamente na tela do perfil. Mas, em nosso sistema interno, o perfil é confirmado e você aparece normalmente para os pacientes.\n\nA renovação por Pix precisa ser feita manualmente todo mês.\n\nPor favor, envie o comprovante do Pix como imagem ou documento para conferirmos a renovação.",
      "input": "Imagem ou documento",
      "transitions": [
        {
          "target": "renovacao_pix_recebida",
          "conditions": []
        }
      ],
      "title": "Reenvio das instruções de renovação por Pix"
    },
    "renovacao_pix_recebida": {
      "description": "Confirmação de recebimento do comprovante de renovação por Pix.",
      "message": "Obrigado.\nRecebemos seu comprovante de renovação por Pix e vamos conferir o pagamento.\nRetornaremos assim que a renovação for confirmada.",
      "end": true,
      "title": "Recebimento do comprovante de renovação por Pix"
    },
    "falar_atendente": {
      "description": "Coleta de contexto antes do atendimento humano.",
      "actions": [
        "postgres_set_manual_chat_mode"
      ],
      "message": "Conte para a gente o contexto da sua solicitação.\n\nAssim que você enviar, a conversa será encaminhada para nossa equipe.\n\n*Importante:* nosso atendimento funciona apenas em dias úteis.\n\nCaso queira voltar ao início antes de enviar o contexto, digite RESET.",
      "transitions": [
        {
          "target": "falar_atendente_recebido",
          "conditions": []
        }
      ],
      "title": "Contexto antes do atendimento humano"
    },
    "falar_atendente_recebido": {
      "description": "Confirmação do encaminhamento para atendimento humano.",
      "message": "Obrigado pelas informações.\nSua conversa foi encaminhada para nossa equipe. Um atendente responderá assim que possível.",
      "end": true,
      "title": "Encaminhamento para atendimento humano"
    },
    "solicitar_reposicao": {
      "description": "Solicitação de comprovantes para reposição.",
      "message": "Para solicitar uma reposição, envie uma *GRAVAÇÃO DE TELA*, sem edição e sem recortes, de data recente, que demonstre que o paciente não respondeu dentro de 15 dias.\n\nEnvie o vídeo diretamente aqui pelo WhatsApp.\n\nApós o envio da gravação, perguntaremos ao paciente se houve resposta, para evitar fraudes. Em até 7 dias úteis, te enviaremos uma reposição.\n\n*Importante:* nosso atendimento funciona apenas em dias úteis.",
      "input": "Vídeo",
      "transitions": [
        {
          "target": "reposicao_contexto",
          "conditions": []
        }
      ],
      "title": "Comprovantes para reposição"
    },
    "reposicao_contexto": {
      "description": "Coleta de informações adicionais para a reposição.",
      "message": "Recebemos o vídeo. Se houver alguma informação que possa ajudar na análise, envie agora.\n\nQuando concluir, clique em \"Enviei tudo\".",
      "buttons": [
        "Enviei tudo"
      ],
      "transitions": [
        {
          "target": "reposicao_recebida",
          "conditions": [
            "enviei tudo"
          ]
        },
        {
          "target": "reposicao_contexto_adicional",
          "conditions": []
        }
      ],
      "title": "Informações adicionais para a reposição"
    },
    "reposicao_contexto_adicional": {
      "description": "Continuação da coleta de informações para a reposição.",
      "message": "Informação adicionada. Se quiser, envie outro complemento em texto, imagem, documento ou vídeo.\n\nQuando não precisar acrescentar mais nada, clique em \"Enviei tudo\".",
      "buttons": [
        "Enviei tudo"
      ],
      "transitions": [
        {
          "target": "reposicao_recebida",
          "conditions": [
            "enviei tudo"
          ]
        },
        {
          "target": "reposicao_contexto_adicional",
          "conditions": []
        }
      ],
      "title": "Continuação da coleta de informações para a reposição"
    },
    "reposicao_recebida": {
      "description": "Confirmação de recebimento da solicitação de reposição.",
      "message": "Obrigado.\nSua solicitação foi recebida e será analisada pela equipe responsável.\nRetornaremos assim que a análise for concluída.",
      "end": true,
      "title": "Recebimento da solicitação de reposição"
    },
    "lgpd": {
      "description": "Aviso de privacidade antes da coleta de dados.",
      "message": "Antes de prosseguirmos, informamos que os dados fornecidos serão utilizados para avaliação do seu cadastro profissional e eventual formalização de parceria com a Rede MetAMORfose.\n\nAo continuar, você declara estar ciente de nossa Política de Privacidade, e termos de uso\n\nPor favor assine em orgmetamorfose.com.br/termos",
      "buttons": [
        "Assinei"
      ],
      "transitions": [
        {
          "target": "explicacao_rede",
          "conditions": [
            "assinei"
          ]
        }
      ],
      "title": "Aviso de privacidade antes da coleta de dados"
    },
    "explicacao_rede": {
      "description": "Explicação breve sobre funcionamento da Rede.",
      "actions": [
        "redis_create_professional_stage"
      ],
      "message": "A Rede MetAMORfose conecta profissionais de saúde a pacientes que buscam atendimento online.\n\nComo funciona:\n- Você define o valor da sua consulta.\n- O paciente paga diretamente a você.\n- Você recebe o WhatsApp dos pacientes via e-mail, tem autonomia para combinar agenda, duração, ferramenta de atendimento e forma de pagamento.\n\nNossa mensalidade cobre a divulgação do seu perfil e o envio de conexões com pacientes. Os planos são:\n\n- Premium - R$190/mês: perfil + 4 conexões com pacientes.\n- Platinum - R$570/mês: perfil + 12 conexões com pacientes.\n- Gold - R$1.190/mês: perfil + mais de 20 conexões com pacientes, em número variável.\n\nNosso site é orgmetamorfose.com.br\n\nSe, após a análise do processo seletivo, seu cadastro profissional não for aceito, o valor pago será reembolsado integralmente.\n\nGostaria de continuar?",
      "buttons": [
        "Prosseguir"
      ],
      "transitions": [
        {
          "target": "nome_completo",
          "conditions": [
            "prosseguir"
          ]
        }
      ],
      "title": "Apresentação da Rede MetAMORfose"
    },
    "nome_completo": {
      "description": "Coleta do nome completo.",
      "actions": [
        "redis_update_professional_name",
        "postgres_update_person_name"
      ],
      "message": "Qual é o seu nome completo?",
      "input": "Texto",
      "transitions": [
        {
          "target": "email_profissional",
          "conditions": []
        }
      ],
      "title": "Nome completo"
    },
    "email_profissional": {
      "description": "Coleta do e-mail profissional.",
      "actions": [
        "redis_update_professional_email"
      ],
      "message": "Qual é o seu e-mail?",
      "input": "Texto",
      "transitions": [
        {
          "target": "area_atuacao",
          "conditions": []
        }
      ],
      "title": "E-mail profissional"
    },
    "area_atuacao": {
      "description": "Coleta da área principal de atuação.",
      "actions": [
        "redis_update_professional_area"
      ],
      "message": "Qual é sua principal área de atuação?",
      "buttons": [
        "Nutrição",
        "Clínico geral",
        "Psiquiatria",
        "Psicoterapia",
        "Psicanálise",
        "Terapia holística",
        "Outra"
      ],
      "transitions": [
        {
          "target": "orientacao_medica_rqe",
          "conditions": [
            "clinico geral",
            "psiquiatria"
          ]
        },
        {
          "target": "abordagem_psicoterapia",
          "conditions": [
            "psicoterapia"
          ]
        },
        {
          "target": "genero",
          "conditions": [
            "nutricao",
            "psicanalise",
            "terapia holistica"
          ]
        },
        {
          "target": "area_atuacao_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Área principal de atuação"
    },
    "area_atuacao_outro": {
      "description": "Coleta textual de outra área de atuação.",
      "actions": [
        "redis_update_professional_area"
      ],
      "message": "Escreva sua área de atuação.",
      "input": "Texto",
      "transitions": [
        {
          "target": "genero",
          "conditions": []
        }
      ],
      "title": "Coleta textual de outra área de atuação"
    },
    "orientacao_medica_rqe": {
      "description": "Explicação específica para profissionais médicos sobre CRM e RQE.",
      "message": "Para profissionais médicos:\n\nNão é necessário possuir RQE para se cadastrar. Um médico com CRM ativo pode atender em diferentes áreas, mas sem RQE não deve se anunciar como especialista.\n\nPor exemplo: um médico sem RQE em psiquiatria pode atuar como clínico geral atendendo demandas de saúde mental, mas não deve se apresentar como psiquiatra especialista.\n\nPedimos apenas transparência na apresentação aos pacientes.",
      "buttons": [
        "Entendi"
      ],
      "transitions": [
        {
          "target": "genero",
          "conditions": [
            "entendi"
          ]
        }
      ],
      "title": "Explicação específica para profissionais médicos sobre CRM e RQE"
    },
    "abordagem_psicoterapia": {
      "description": "Coleta da abordagem principal para profissionais de psicoterapia.",
      "actions": [
        "redis_update_professional_approach"
      ],
      "message": "Qual é sua abordagem principal na psicoterapia?",
      "buttons": [
        "TCC",
        "Psicanálise",
        "Outra"
      ],
      "transitions": [
        {
          "target": "genero",
          "conditions": [
            "tcc",
            "psicanalise"
          ]
        },
        {
          "target": "abordagem_psicoterapia_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Abordagem principal para profissionais de psicoterapia"
    },
    "abordagem_psicoterapia_outro": {
      "description": "Coleta textual de outra abordagem.",
      "actions": [
        "redis_update_professional_approach"
      ],
      "message": "Escreva sua abordagem principal.",
      "input": "Texto",
      "transitions": [
        {
          "target": "genero",
          "conditions": []
        }
      ],
      "title": "Coleta textual de outra abordagem"
    },
    "genero": {
      "description": "Coleta de gênero.",
      "actions": [
        "redis_update_professional_gender"
      ],
      "message": "Como você se identifica?",
      "buttons": [
        "Homem",
        "Mulher",
        "Homem trans",
        "Mulher trans",
        "Prefiro não informar"
      ],
      "transitions": [
        {
          "target": "identificacao",
          "conditions": [
            "homem",
            "mulher",
            "homem trans",
            "mulher trans",
            "prefiro nao informar"
          ]
        }
      ],
      "title": "Gênero"
    },
    "identificacao": {
      "description": "Coleta de identificação social ou grupo minorizado.",
      "actions": [
        "redis_update_professional_minority_group"
      ],
      "message": "Você se identifica com algum desses grupos?",
      "buttons": [
        "Negro",
        "Negro LGBT",
        "LGBT",
        "Prefiro não informar"
      ],
      "transitions": [
        {
          "target": "ferramenta_online",
          "conditions": [
            "negro",
            "negro lgbt",
            "lgbt",
            "prefiro nao informar"
          ]
        }
      ],
      "title": "Identificação social ou grupo minorizado"
    },
    "ferramenta_online": {
      "description": "Coleta da ferramenta usada para atendimento online.",
      "actions": [
        "redis_update_professional_video_tool"
      ],
      "message": "Qual ferramenta costuma utilizar para os atendimentos online?\n\nNossa parceria visa promover seu perfil profissional e garantir a conexão com pacientes que buscam ativamente por atendimento. Nós promovemos seu perfil, e conexões com pacientes - mas não interferimos nos agendamentos, ou quantidade de sessões fechadas. Como garantia, nós repomos pacientes que não respondem em até 15 dias (válido o número de reposições pelo número de conexões do plano - é necessário nos enviar gravação de tela de data recente, sem recortes e sem edição). Pacientes que responderam ou estão na fase de negociação de valores nós não repomos. A intenção com essa garantia é que nossos profissionais tenham retorno, e todos os pacientes cadastrados sejam atendidos.",
      "buttons": [
        "Google Meet",
        "Zoom",
        "WhatsApp",
        "Outra"
      ],
      "transitions": [
        {
          "target": "comprovante_registro",
          "conditions": [
            "google meet",
            "zoom",
            "whatsapp"
          ]
        },
        {
          "target": "ferramenta_online_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Ferramenta usada para atendimento online"
    },
    "ferramenta_online_outro": {
      "description": "Coleta textual de outra ferramenta online.",
      "actions": [
        "redis_update_professional_video_tool"
      ],
      "message": "Escreva qual ferramenta utiliza.",
      "input": "Texto",
      "transitions": [
        {
          "target": "comprovante_registro",
          "conditions": []
        }
      ],
      "title": "Coleta textual de outra ferramenta online"
    },
    "resumo_dados": {
      "description": "Confirmação dos dados antes da escolha do plano.",
      "message": "Os dados estão corretos?",
      "buttons": [
        "Confirmar",
        "Corrigir"
      ],
      "transitions": [
        {
          "target": "cadastro_postgres",
          "conditions": [
            "confirmar"
          ]
        },
        {
          "target": "escolha_correcao",
          "conditions": [
            "corrigir"
          ]
        }
      ],
      "title": "Confirmação dos dados antes da escolha do plano"
    },
    "comprovante_registro": {
      "description": "Solicitação de comprovante do registro, formação ou certificação.",
      "actions": [
        "redis_update_professional_council_registration_document"
      ],
      "message": "Agora envie uma foto, imagem ou documento que comprove seu registro, formação ou certificação profissional.\n\nPode ser carteira do conselho, certificado, declaração, diploma ou outro documento relacionado à sua atuação.\n\nCaso não possua registro em conselho profissional, toque em \"Sem registro\" para continuar.\n\n*Atenção:* se você atua como médico, nutricionista ou psicólogo, é obrigatório possuir registro ativo no respectivo conselho profissional. Caso selecione \"Sem registro\", seu cadastro será recusado.",
      "buttons": [
        "Sem registro"
      ],
      "input": "Imagem ou documento",
      "transitions": [
        {
          "target": "profissional_data_nascimento",
          "conditions": [
            "sem registro"
          ]
        },
        {
          "target": "profissional_data_nascimento",
          "conditions": []
        }
      ],
      "title": "Comprovante do registro, formação ou certificação"
    },
    "profissional_data_nascimento": {
      "description": "Coleta e valida a data de nascimento do profissional.",
      "actions": [
        "redis_update_professional_birth_date"
      ],
      "message": "Qual é a sua data de nascimento? Envie no formato DD/MM/AAAA. Exemplo: 15/08/1990.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Data de nascimento do profissional"
    },
    "cadastro_postgres": {
      "description": "Apresenta planos antes do pagamento.",
      "message": "A Rede de Telemedicina da MetAMORfose nasceu em 2020 pela necessidade de se ter uma solução de fácil acesso a consultas de saúde e programas de bem estar para as pessoas. Em 2023 recebemos investimento em nome de Luiza Fogaça pela Agência USP de Inovação para desenvolver a MetAMORfose na Europa, enquanto em 2024 recebemos mentoria de desenvolvimento pela Google for Startups, e em 2025 pela Microsoft for Startups Founders Hub: https://www.orgmetamorfose.com.br/missao\n\nAgência USP de Inovação: https://www.inovacao.usp.br/editalbolsa2023/\n\nPara preencher uma das vagas disponíveis e começar a receber conexões com pacientes, o próximo passo é escolher o plano de parceria.\n\n- Premium – R$190/mês: Perfil + 4 conexões com pacientes\n- Platinum – R$570/mês: Perfil + 12 conexões\n- Gold – R$1.190/mês: Perfil + mais de 20 conexões (número variável de conexões)\n\nSe o cadastro não for aceito no processo seletivo, o pagamento será reembolsado integralmente.\n\nQual modalidade você escolhe para preencher a vaga?",
      "buttons": [
        "Premium",
        "Platinum",
        "Gold"
      ],
      "transitions": [
        {
          "target": "selecao_profissional_pagamento",
          "conditions": [
            "premium",
            "platinum",
            "gold"
          ]
        }
      ],
      "title": "Escolha do plano profissional"
    },
    "escolha_correcao": {
      "description": "Escolha de qual informação será corrigida.",
      "message": "Qual informação você gostaria de corrigir?",
      "buttons": [
        "Nome",
        "E-mail",
        "Área",
        "Abordagem",
        "Gênero",
        "Identificação",
        "Ferramenta",
        "Comprovante",
        "Data de nascimento"
      ],
      "transitions": [
        {
          "target": "corrigir_nome",
          "conditions": [
            "nome"
          ]
        },
        {
          "target": "corrigir_email",
          "conditions": [
            "e-mail",
            "email"
          ]
        },
        {
          "target": "corrigir_area",
          "conditions": [
            "area"
          ]
        },
        {
          "target": "corrigir_abordagem",
          "conditions": [
            "abordagem"
          ]
        },
        {
          "target": "corrigir_genero",
          "conditions": [
            "genero"
          ]
        },
        {
          "target": "corrigir_identificacao",
          "conditions": [
            "identificacao"
          ]
        },
        {
          "target": "corrigir_ferramenta",
          "conditions": [
            "ferramenta"
          ]
        },
        {
          "target": "corrigir_comprovante",
          "conditions": [
            "comprovante"
          ]
        },
        {
          "target": "corrigir_data_nascimento",
          "conditions": [
            "data de nascimento"
          ]
        }
      ],
      "title": "Qual informação será corrigida"
    },
    "corrigir_data_nascimento": {
      "description": "Correção da data de nascimento do profissional.",
      "actions": [
        "redis_correct_professional_birth_date"
      ],
      "message": "Digite a data de nascimento correta no formato DD/MM/AAAA. Exemplo: 15/08/1990.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Data de nascimento do profissional"
    },
    "corrigir_nome": {
      "description": "Correção do nome completo.",
      "actions": [
        "redis_update_professional_name",
        "postgres_update_person_name",
        "redis_get_professional_stage_summary"
      ],
      "message": "Digite o nome completo correto.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Nome completo"
    },
    "corrigir_email": {
      "description": "Correção do e-mail profissional.",
      "actions": [
        "redis_update_professional_email",
        "redis_get_professional_stage_summary"
      ],
      "message": "Digite o e-mail correto.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "E-mail profissional"
    },
    "corrigir_area": {
      "description": "Correção da área principal de atuação.",
      "actions": [
        "redis_update_professional_area",
        "redis_get_professional_stage_summary"
      ],
      "message": "Qual é a área principal de atuação correta?",
      "buttons": [
        "Nutrição",
        "Clínico geral",
        "Psiquiatria",
        "Psicoterapia",
        "Psicanálise",
        "Terapia holística",
        "Outra"
      ],
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": [
            "nutricao",
            "clinico geral",
            "psiquiatria",
            "psicoterapia",
            "psicanalise",
            "terapia holistica"
          ]
        },
        {
          "target": "corrigir_area_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Área principal de atuação"
    },
    "corrigir_area_outro": {
      "description": "Correção textual da área de atuação.",
      "actions": [
        "redis_update_professional_area",
        "redis_get_professional_stage_summary"
      ],
      "message": "Escreva a área de atuação correta.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Correção textual da área de atuação"
    },
    "corrigir_abordagem": {
      "description": "Correção da abordagem principal.",
      "actions": [
        "redis_update_professional_approach",
        "redis_get_professional_stage_summary"
      ],
      "message": "Qual é a abordagem principal correta?",
      "buttons": [
        "TCC",
        "Psicanálise",
        "Não se aplica",
        "Outra"
      ],
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": [
            "tcc",
            "psicanalise",
            "nao se aplica"
          ]
        },
        {
          "target": "corrigir_abordagem_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Abordagem principal"
    },
    "corrigir_abordagem_outro": {
      "description": "Correção textual da abordagem.",
      "actions": [
        "redis_update_professional_approach",
        "redis_get_professional_stage_summary"
      ],
      "message": "Escreva a abordagem correta.",
      "input": "Texto",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Correção textual da abordagem"
    },
    "corrigir_genero": {
      "description": "Correção do gênero.",
      "actions": [
        "redis_update_professional_gender",
        "redis_get_professional_stage_summary"
      ],
      "message": "Como você se identifica?",
      "buttons": [
        "Homem",
        "Mulher",
        "Homem trans",
        "Mulher trans",
        "Prefiro não informar"
      ],
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Gênero"
    },
    "corrigir_identificacao": {
      "description": "Correção da identificação social ou grupo minorizado.",
      "actions": [
        "redis_update_professional_minority_group",
        "redis_get_professional_stage_summary"
      ],
      "message": "Você se identifica com algum desses grupos?",
      "buttons": [
        "Negro",
        "Negro LGBT",
        "LGBT",
        "Prefiro não informar"
      ],
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": [
            "negro",
            "negro lgbt",
            "lgbt",
            "prefiro nao informar"
          ]
        }
      ],
      "title": "Identificação social ou grupo minorizado"
    },
    "corrigir_ferramenta": {
      "description": "Correção da ferramenta de atendimento online.",
      "actions": [
        "redis_update_professional_video_tool"
      ],
      "message": "Qual ferramenta correta você costuma utilizar para atendimentos online?\n\nNossa parceria visa promover seu perfil profissional e garantir a conexão com pacientes que buscam ativamente por atendimento. Nós promovemos seu perfil, e conexões com pacientes - mas não interferimos nos agendamentos, ou quantidade de sessões fechadas. Como garantia, nós repomos pacientes que não respondem em até 15 dias (válido o número de reposições pelo número de conexões do plano - é necessário nos enviar gravação de tela de data recente, sem recortes e sem edição). Pacientes que responderam ou estão na fase de negociação de valores nós não repomos. A intenção com essa garantia é que nossos profissionais tenham retorno, e todos os pacientes cadastrados sejam atendidos.",
      "buttons": [
        "Google Meet",
        "Zoom",
        "WhatsApp",
        "Outra"
      ],
      "transitions": [
        {
          "target": "corrigir_comprovante",
          "conditions": [
            "google meet",
            "zoom",
            "whatsapp"
          ]
        },
        {
          "target": "corrigir_ferramenta_outro",
          "conditions": [
            "outra"
          ]
        }
      ],
      "title": "Ferramenta de atendimento online"
    },
    "corrigir_ferramenta_outro": {
      "description": "Correção textual da ferramenta online.",
      "actions": [
        "redis_update_professional_video_tool"
      ],
      "message": "Escreva a ferramenta correta.",
      "input": "Texto",
      "transitions": [
        {
          "target": "corrigir_comprovante",
          "conditions": []
        }
      ],
      "title": "Correção textual da ferramenta online"
    },
    "corrigir_comprovante": {
      "description": "Correção do comprovante de registro, formação ou certificação.",
      "actions": [
        "redis_update_professional_council_registration_document",
        "redis_get_professional_stage_summary"
      ],
      "message": "Envie novamente a foto, imagem ou documento correto.\n\nCaso não tenha registro profissional, toque em \"Sem registro\" para continuar.\n\n*Atenção:* se você atua como médico, nutricionista ou psicólogo, é obrigatório possuir registro ativo no respectivo conselho profissional. Caso selecione \"Sem registro\", seu cadastro será recusado.",
      "buttons": [
        "Sem registro"
      ],
      "input": "Imagem ou documento",
      "transitions": [
        {
          "target": "resumo_dados",
          "conditions": [
            "sem registro"
          ]
        },
        {
          "target": "resumo_dados",
          "conditions": []
        }
      ],
      "title": "Comprovante de registro, formação ou certificação"
    },
    "selecao_profissional_pagamento": {
      "description": "Coleta do comprovante de pagamento.",
      "actions": [
        "postgres_register_professional_application",
        "sheets_register_professional",
        "postgres_set_professional_registration_state"
      ],
      "message": "Certo. Como você prefere? Via pix ou crédito? Via pix está em nome de Luiza Fogaça, a gestora da plataforma. A chave pix: contato@orgmetamorfose.com\n\nSe preferir por crédito no site, a assinatura é faturada mensalmente no mesmo dia - mas você pode cancelar a qualquer momento se quiser - o link é https://orgmetamorfose.com.br/assinatura\n\nComo o pagamento via Pix é feito fora do site, o sistema não consegue atualizar o selo de \"ativo\" automaticamente na tela do perfil. Mas, em nosso sistema interno, o perfil é confirmado e você aparece normalmente para os pacientes.\n\nA única diferença prática é:\n- No Cartão: A renovação é automática.\n- No Pix: É necessário fazer o pagamento manualmente todo mês para renovar. Independentemente disso, seu acesso e o recebimento de novos pacientes estão totalmente garantidos.\n\nSe, após a análise do processo seletivo, seu cadastro profissional não for aceito, o valor pago será reembolsado integralmente.\n\nPor favor, envie o comprovante do Pix como imagem ou documento para finalizarmos a conferência.",
      "input": "Imagem ou documento",
      "transitions": [
        {
          "target": "video_pos_pagamento",
          "conditions": []
        }
      ],
      "title": "Comprovante de pagamento"
    },
    "video_pos_pagamento": {
      "description": "Coleta do vídeo de qualificação após o pagamento.",
      "actions": [
        "postgres_update_professional_qualification"
      ],
      "message": "Quer ganhar mais 2 conexões com pacientes neste mês? Grave um vídeo de até um minuto sobre sua graduação, pós-graduação, certificados, abordagem teórica, experiência clínica ou outras informações relevantes para avaliação do cadastro - e, no final do vídeo, diga por que a MetAMORfose se alinha com sua experiência.\n\nApós a gravação com o rosto visível - precisamos garantir que é você -, envie o seu vídeo diretamente aqui pelo WhatsApp.\n\nAo nos enviar o vídeo, você declara que todas as informações são verdadeiras e firma cessão de direitos, de forma expressa, gratuita, irrevogável e irretratável, de sua imagem, voz e vídeo, para veiculação pelo prazo de 180 dias (redes sociais da empresa, portfólio interno e campanhas publicitárias), em conformidade com a LGPD (Lei nº 13.709/2018).",
      "buttons": [
        "Não tenho interesse"
      ],
      "input": "Vídeo",
      "transitions": [
        {
          "target": "selecao_profissional_end",
          "conditions": [
            "nao tenho interesse"
          ]
        },
        {
          "target": "selecao_profissional_end",
          "conditions": []
        }
      ],
      "title": "Vídeo de qualificação após o pagamento"
    },
    "selecao_profissional_end": {
      "description": "Encerramento do fluxo de seleção profissional.",
      "message": "Obrigada. Boas vindas ao nosso time da Rede MetAMORfose.\n\nO próximo passo é criar seu perfil profissional em: https://www.orgmetamorfose.com.br/account/my-account\n\nFinalizado o perfil, após 7 dias, as conexões com pacientes serão enviadas para o e-mail informado pelo endereço: no-reply@orgmetamorfosepro.com\n\nNós promovemos seu perfil e realizamos as conexões com pacientes, mas não interferimos nos agendamentos ou quantidade de sessões fechadas. Vamos verificar seu pagamento e seu registro e te retornamos. Você tem alguma dúvida?",
      "buttons": [
        "Enviar feedback",
        "Dúvidas",
        "Encerrar"
      ],
      "transitions": [
        {
          "target": "feedback_inicio",
          "conditions": [
            "enviar feedback"
          ]
        },
        {
          "target": "faq_inicio",
          "conditions": [
            "duvidas"
          ]
        },
        {
          "target": "selecao_profissional_finalizado",
          "conditions": [
            "encerrar"
          ]
        }
      ],
      "title": "Encerramento do fluxo de seleção profissional"
    },
    "selecao_profissional_finalizado": {
      "description": "Finalização do fluxo de seleção profissional.",
      "message": "Atendimento encerrado. Obrigada pelo contato.",
      "end": true,
      "title": "Finalização do fluxo de seleção profissional"
    }
  }
}
""")


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(character for character in normalized if not unicodedata.combining(character))


def _fallback_input_types(key: str, node: dict[str, object]) -> list[str]:
    configured = node.get("input")
    if key in {"email_profissional", "corrigir_email"}:
        return ["EMAIL"]
    if "data_nascimento" in key:
        return ["DATE"]
    if configured == "Texto":
        return ["TEXT"]
    if configured == "Imagem ou documento":
        return ["IMAGE", "DOCUMENT"]
    if configured == "Vídeo":
        return ["VIDEO"]
    return ["AUTO"]


def upgrade() -> None:
    node_enum = postgresql.ENUM("START", "MESSAGE", "END", name="node_type", schema=SCHEMA, create_type=False)
    input_enum = postgresql.ENUM(
        "TEXT", "EMAIL", "DATE", "NUMBER", "IMAGE", "DOCUMENT", "VIDEO", "AUTO",
        name="input_type", schema=SCHEMA, create_type=False,
    )
    node_table = sa.table(
        "node",
        sa.column("id", sa.Integer()), sa.column("key", sa.String()), sa.column("type", node_enum),
        sa.column("title", sa.String()), sa.column("description", sa.Text()),
        sa.column("message", sa.Text()), sa.column("position", sa.Integer()), schema=SCHEMA,
    )
    transition_table = sa.table(
        "transition",
        sa.column("id", sa.Integer()), sa.column("node_id", sa.Integer()),
        sa.column("input_type", input_enum), sa.column("expected_value", sa.String()),
        sa.column("button_label", sa.String()), sa.column("next_node_id", sa.Integer()),
        sa.column("position", sa.Integer()), schema=SCHEMA,
    )
    action_table = sa.table(
        "transition_action",
        sa.column("transition_id", sa.Integer()), sa.column("action_key", sa.String()),
        sa.column("config", postgresql.JSONB()), sa.column("is_required", sa.Boolean()), schema=SCHEMA,
    )
    error_table = sa.table(
        "input_error_message",
        sa.column("input_type", input_enum), sa.column("message", sa.Text()), schema=SCHEMA,
    )

    connection = op.get_bind()
    nodes = FLOW_DATA["nodes"]
    ids: dict[str, int] = {}
    for position, (key, node) in enumerate(nodes.items()):
        node_type = "START" if key == "start" else "END" if node.get("end", False) else "MESSAGE"
        ids[key] = connection.execute(node_table.insert().values(
            key=key, type=node_type, title=node["title"], description=node.get("description"),
            message=node["message"], position=position,
        ).returning(node_table.c.id)).scalar_one()

    for key, node in nodes.items():
        used_buttons: set[str] = set()
        transition_position = 0
        buttons = node.get("buttons", [])
        for source_transition in node.get("transitions", []):
            conditions = source_transition.get("conditions", [])
            specs: list[tuple[str, str | None]] = (
                [("TEXT", condition) for condition in conditions]
                if conditions else
                [(input_type, None) for input_type in _fallback_input_types(key, node)]
            )
            for input_type, expected_value in specs:
                button_label = None
                if expected_value is not None:
                    normalized_expected = _normalize(expected_value)
                    for button in buttons:
                        if button not in used_buttons and _normalize(button) == normalized_expected:
                            button_label = button
                            used_buttons.add(button)
                            break
                transition_id = connection.execute(transition_table.insert().values(
                    node_id=ids[key], input_type=input_type, expected_value=expected_value,
                    button_label=button_label, next_node_id=ids[source_transition["target"]],
                    position=transition_position,
                ).returning(transition_table.c.id)).scalar_one()
                transition_position += 1
                for action_key in node.get("actions", []):
                    connection.execute(action_table.insert().values(
                        transition_id=transition_id, action_key=action_key, config=None,
                        is_required=action_key not in OPTIONAL_ACTIONS,
                    ))

    op.bulk_insert(error_table, [
        {"input_type": input_type, "message": message}
        for input_type, message in INPUT_ERRORS.items()
    ])


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM chatbot_flow.transition_action"))
    connection.execute(sa.text("DELETE FROM chatbot_flow.transition"))
    connection.execute(sa.text("DELETE FROM chatbot_flow.node"))
    connection.execute(sa.text("DELETE FROM chatbot_flow.input_error_message"))
