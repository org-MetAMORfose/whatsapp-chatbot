# Dados de matching em JSONB

Esta etapa adiciona `professional.matching_profile` e `patient.matching_request` como
JSONB. `matching_slot.score_breakdown` continua registrando a explicação do resultado.
O fluxo salvo no esquema `chatbot_flow` não é alterado.

## Contrato inicial

```json
{
  "schema_version": 1,
  "areas": ["Psicoterapia", "Psiquiatria"],
  "psychotherapy": {
    "approaches": ["TCC", "Psicanálise"],
    "specialties": ["Autismo", "TDAH", "Bipolaridade", "Borderline", "Ansiedade", "Depressão"]
  },
  "profile": {"gender": "Mulher", "race": "Negra", "lgbtqiapn_plus": true}
}
```

O JSON acima é o perfil de um profissional. Uma solicitação de paciente usa:

```json
{
  "schema_version": 1,
  "area": "Psicoterapia",
  "psychotherapy": {"approach": null, "specialties": []},
  "professional_preferences": {"gender": null, "race": null, "lgbtqiapn_plus": null}
}
```

`approach: null` significa que o paciente aceita Psicoterapia sem preferência de
abordagem. Profissional com `approaches: []` também pode atendê-lo; não atende uma
solicitação que exija especificamente TCC ou Psicanálise. Especialidades, gênero e
autodeclaração são preferências que influenciam a ordem, sem eliminar candidatos.
Especialidades aceitam qualquer texto e só se aplicam a Psicoterapia; a lista
sugerida nos formulários não restringe a API. LGBTQIAPN+ participa como especialidade
de atendimento, sem inferência pela identidade do profissional. Os campos legados
`profile.lgbtqiapn_plus` e `professional_preferences.lgbtqiapn_plus` continuam no
contrato de armazenamento, mas são ignorados na pontuação e na explicação do
resultado. Não há alteração do banco nem conversão dos registros existentes nesta
mudança.

## Migração e compatibilidade

`0015_matching_json_profiles` adiciona os JSONs e converte os registros existentes.
O valor legado de `area` é levado para `areas` ou `area`; `Psicanálise` passa a
ser área `Psicoterapia` com abordagem `Psicanálise`. A migração também aproveita
abordagem, gênero e grupo minorizado que já estavam preenchidos. `NULL` e dados
não reconhecidos continuam sem preferência ou sem abordagem conhecida.

As colunas antigas (`professional.area`, `approach`, `gender`, `minority_group` e
`patient.area`, `psychotherapy_approach`, `professional_profile`) são mantidas
temporariamente. Algumas integrações e a notificação ainda usam os valores de
área. **Pedir depois outra migration** para removê-las, após verificar que todos
os caminhos de escrita e leitura foram transferidos para os JSONs e que os dados
migrados estão corretos. A remoção não faz parte desta entrega.

## CSV de revisão

`secrets/import_professionals_review.py --dry-run` classifica o CSV sem acessar o
banco, gera `secrets/profissionais_revisar2.csv` com as linhas de uma área e relata
as linhas elegíveis ou ignoradas. Reexecução com o mesmo arquivo é segura. A
importação usa `DATABASE_URL` do ambiente e exige confirmação ou `--yes`.
O campo `ativo 1 inativo 0` é ignorado, conforme a decisão para esta revisão.
Telefone duplicado, inválido, e-mail inválido e motivo adicional impedem a
importação da linha. A identificação LGBTQIAPN+ indicada na área é convertida
para o perfil do profissional. O CSV não contém as seis especialidades clínicas.

O fluxo atual não pergunta pelas seis condições nem separadamente por gênero,
raça e sexualidade. As actions novas estão disponíveis em `GET /chatbot-flow/actions`
para uma configuração futura; nenhum nó ou transição foi alterado nesta etapa.
