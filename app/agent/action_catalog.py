"""Actions that administrators may add to a chatbot graph."""

from typing import Any, Final

from pydantic import BaseModel

from app.agent.chat_flow import SheetsFlushConfig, SheetsStoreAnswerConfig

SHEETS_STORE_ANSWER: Final = "sheets_store_answer"
SHEETS_FLUSH: Final = "sheets_flush"

CONFIG_MODELS: Final[dict[str, type[BaseModel]]] = {
    SHEETS_STORE_ANSWER: SheetsStoreAnswerConfig,
    SHEETS_FLUSH: SheetsFlushConfig,
}
MANAGED_ACTION_KEYS: Final[frozenset[str]] = frozenset(CONFIG_MODELS)


def validate_managed_action_config(action_key: str, config: object) -> BaseModel:
    try:
        model = CONFIG_MODELS[action_key]
    except KeyError as exc:
        raise ValueError(f"Action não administrável: {action_key}") from exc
    return model.model_validate(config)


def action_catalog() -> dict[str, list[dict[str, Any]]]:
    return {
        "actions": [
            {
                "key": SHEETS_STORE_ANSWER,
                "label": "Guardar resposta",
                "description": "Guarda a resposta desta pergunta em uma coluna do Google Sheets.",
                "config_type": SHEETS_STORE_ANSWER,
                "default_is_required": True,
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
                "default_is_required": True,
                "parameters": [
                    {"key": "tab", "label": "Nome da aba", "type": "string", "required": True},
                ],
            },
        ]
    }
