"""Actions that administrators may add to a chatbot graph."""

from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from app.agent.chat_flow import SheetsFlushConfig, SheetsStoreAnswerConfig

SHEETS_STORE_ANSWER: Final = "sheets_store_answer"
SHEETS_FLUSH: Final = "sheets_flush"
REDIS_MATCHING_ACTIONS: Final = (
    ("redis_update_professional_psychotherapy_specialties", "Experiência clínica do profissional"),
    ("redis_update_professional_race", "Raça do profissional"),
    ("redis_update_professional_lgbtqiapn_plus", "Identificação LGBTQIAPN+ do profissional"),
    ("redis_update_patient_psychotherapy_specialties", "Condição desejada pelo paciente"),
    ("redis_update_patient_preferred_gender", "Gênero preferido do profissional"),
    ("redis_update_patient_preferred_race", "Raça preferida do profissional"),
    ("redis_update_patient_prefers_lgbtqiapn_plus", "Preferência LGBTQIAPN+"),
)


class NoConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


CONFIG_MODELS: Final[dict[str, type[BaseModel]]] = {
    SHEETS_STORE_ANSWER: SheetsStoreAnswerConfig,
    SHEETS_FLUSH: SheetsFlushConfig,
    **{key: NoConfig for key, _ in REDIS_MATCHING_ACTIONS},
}
MANAGED_ACTION_KEYS: Final[frozenset[str]] = frozenset(CONFIG_MODELS)


def validate_managed_action_config(action_key: str, config: object) -> BaseModel:
    try:
        model = CONFIG_MODELS[action_key]
    except KeyError as exc:
        raise ValueError(f"Action não administrável: {action_key}") from exc
    return model.model_validate(config if config is not None else {})


def action_catalog() -> dict[str, list[dict[str, Any]]]:
    return {
        "actions": [
            *[
                {
                    "key": key,
                    "label": label,
                    "description": "Guarda a resposta em Redis para o matching futuro.",
                    "config_type": None,
                    "default_is_required": False,
                    "parameters": [],
                }
                for key, label in REDIS_MATCHING_ACTIONS
            ],
            {
                "key": SHEETS_STORE_ANSWER,
                "label": "Guardar resposta",
                "description": "Guarda a resposta desta pergunta em uma coluna do Google Sheets.",
                "config_type": SHEETS_STORE_ANSWER,
                "default_is_required": False,
                "parameters": [
                    {"key": "tab", "label": "Nome da aba", "type": "string", "required": True},
                    {
                        "key": "column",
                        "label": "Coluna",
                        "type": "string",
                        "required": True,
                        "pattern": "^[A-Z]{1,3}$",
                    },
                ],
            },
            {
                "key": SHEETS_FLUSH,
                "label": "Enviar respostas",
                "description": "Adiciona uma linha com as respostas acumuladas na aba.",
                "config_type": SHEETS_FLUSH,
                "default_is_required": False,
                "parameters": [
                    {"key": "tab", "label": "Nome da aba", "type": "string", "required": True},
                ],
            },
        ]
    }
