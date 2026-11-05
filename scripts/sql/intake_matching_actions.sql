-- Alternativa manual a 0017_intake_matching_actions para executar no DBeaver.
-- Execute o script inteiro, com API e worker parados, junto ao deploy do codigo
-- que acumula especialidades e aceita as novas abordagens.
-- Altera somente actions; preserva tabelas, colunas e versao do fluxo.
-- Nao altera alembic_version. Executar depois a migration nao duplica actions.
-- Faca backup das actions antes: o downgrade da migration preserva os dados.
-- Reinicie o worker atualizado ao terminar para recarregar o cache do fluxo.

BEGIN;

-- Atualiza a action existente para manter a ordem anterior aos resumos.
-- Perfis antigos que combinam genero e identificacao continuam intactos.
UPDATE chatbot_flow.transition_action AS action
SET action_key = 'redis_update_patient_preferred_gender',
    config = COALESCE(NULLIF(action.config, 'null'::jsonb), '{}'::jsonb)
FROM chatbot_flow.transition AS transition, chatbot_flow.node AS node
WHERE action.transition_id = transition.id
  AND transition.node_id = node.id
  AND node.key IN ('paciente_psico_perfil', 'paciente_corrigir_perfil')
  AND lower(transition.expected_value) IN (
      'homem', 'mulher', 'não binário', 'nao binario', 'sem preferência', 'sem preferencia'
  )
  AND action.action_key = 'redis_update_patient_professional_profile';

-- Nos ausentes sao ignorados. Actions existentes nao sao duplicadas.
-- O resumo de correcao e inserido depois da action de autodeclaracao.
WITH action_plan (priority, node_key, action_key) AS (
    VALUES
        (1, 'Qual especialidade quer ser atendido', 'redis_update_patient_psychotherapy_specialties'),
        (1, 'Qual outra especialidade quer ser atendido?', 'redis_update_patient_psychotherapy_specialties'),
        (2, 'Qual especialidade quer atender?', 'redis_update_professional_psychotherapy_specialties'),
        (2, 'Qual outra especialidade quer atender?', 'redis_update_professional_psychotherapy_specialties'),
        (3, 'paciente_psico_perfil', 'redis_update_patient_preferred_gender'),
        (3, 'paciente_corrigir_perfil', 'redis_update_patient_preferred_gender'),
        (4, 'Autodeclaração - por qual profissional você quer ser atendido?', 'redis_update_patient_preferred_race'),
        (4, 'Correção Autodeclaração - por qual profissional você quer ser atendido?', 'redis_update_patient_preferred_race'),
        (5, 'Correção Autodeclaração - por qual profissional você quer ser atendido?', 'redis_get_patient_stage_summary')
)
INSERT INTO chatbot_flow.transition_action (transition_id, action_key, config, is_required)
SELECT transition.id, plan.action_key, '{}'::jsonb, false
FROM action_plan AS plan
JOIN chatbot_flow.node AS node ON node.key = plan.node_key
JOIN chatbot_flow.transition AS transition ON transition.node_id = node.id
WHERE transition.input_type = 'TEXT'
  AND (
      plan.action_key <> 'redis_update_patient_preferred_gender'
      OR lower(transition.expected_value) IN (
          'homem', 'mulher', 'não binário', 'nao binario', 'sem preferência', 'sem preferencia'
      )
  )
  AND NOT EXISTS (
      SELECT 1
      FROM chatbot_flow.transition_action AS action
      WHERE action.transition_id = transition.id
        AND action.action_key = plan.action_key
  )
ORDER BY plan.priority, transition.id;

COMMIT;
