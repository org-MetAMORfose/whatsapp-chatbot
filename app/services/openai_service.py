"""OpenAI API integration used by FAQ retrieval and answer selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from time import perf_counter

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

import app.config.settings as config
from app.repository.sql.faq_knowledge_repository import FaqKnowledgeCandidate

OPENAI_EMBEDDING_DIMENSIONS = 1536
OPENAI_TIMEOUT_SECONDS = 15.0


class OpenAIConfigurationError(RuntimeError):
    """Raised when a required OpenAI setting was not provided."""


class FaqAnswerSelection(BaseModel):
    """Structured selection returned by the response model."""

    selected_entry_id: int | None = Field(
        description=(
            "Identifier of the candidate that answers the question, or null when "
            "none of the candidates is adequate."
        )
    )


@dataclass(frozen=True)
class OpenAIEmbeddingResult:
    embedding: list[float]
    model: str
    input_tokens: int
    latency_ms: int
    raw_response: object


@dataclass(frozen=True)
class OpenAIFaqSelectionResult:
    selected_entry_id: int | None
    response_id: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response: object


class OpenAIService:
    """Generate embeddings and obtain structured decisions from OpenAI."""

    def __init__(
        self,
        client: AsyncOpenAI | None = None,
        *,
        api_key: str | None = None,
        response_model: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._client = client
        self._api_key = config.OPENAI_API_KEY if api_key is None else api_key
        self.response_model = (
            config.OPENAI_RESPONSE_MODEL
            if response_model is None
            else response_model
        )
        self.embedding_model = (
            config.OPENAI_EMBEDDING_MODEL
            if embedding_model is None
            else embedding_model
        )

    async def generate_embedding(self, text: str) -> OpenAIEmbeddingResult:
        """Generate a fixed-size embedding and retain the complete API response."""
        client = self._get_client()
        self._require_setting(self.embedding_model, "OPENAI_EMBEDDING_MODEL")
        started_at = perf_counter()
        response = await client.embeddings.create(
            input=text,
            model=self.embedding_model,
            dimensions=OPENAI_EMBEDDING_DIMENSIONS,
            encoding_format="float",
        )
        latency_ms = round((perf_counter() - started_at) * 1000)

        return OpenAIEmbeddingResult(
            embedding=response.data[0].embedding,
            model=response.model,
            input_tokens=response.usage.prompt_tokens,
            latency_ms=latency_ms,
            raw_response=response,
        )

    async def select_faq_answer(
        self,
        *,
        question: str,
        candidates: list[FaqKnowledgeCandidate],
    ) -> OpenAIFaqSelectionResult:
        """Choose one supplied FAQ entry, without generating a new answer."""
        client = self._get_client()
        self._require_setting(self.response_model, "OPENAI_RESPONSE_MODEL")
        started_at = perf_counter()
        response = await client.responses.parse(
            model=self.response_model,
            instructions=(
                "Select the FAQ candidate that adequately answers the user's "
                "question. Return null when none is adequate. Only select an ID "
                "present in the candidates. Do not write or rewrite an answer."
            ),
            input=self._selection_input(question, candidates),
            text_format=FaqAnswerSelection,
            store=False,
        )
        latency_ms = round((perf_counter() - started_at) * 1000)
        parsed = response.output_parsed
        selected_entry_id = parsed.selected_entry_id if parsed is not None else None
        usage = response.usage

        return OpenAIFaqSelectionResult(
            selected_entry_id=selected_entry_id,
            response_id=response.id,
            model=response.model,
            input_tokens=usage.input_tokens if usage is not None else 0,
            output_tokens=usage.output_tokens if usage is not None else 0,
            latency_ms=latency_ms,
            raw_response=response,
        )

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._require_setting(self._api_key, "OPENAI_API_KEY")
            self._client = AsyncOpenAI(
                api_key=self._api_key,
                timeout=OPENAI_TIMEOUT_SECONDS,
            )
        return self._client

    @staticmethod
    def _selection_input(
        question: str,
        candidates: list[FaqKnowledgeCandidate],
    ) -> str:
        payload = {
            "question": question,
            "candidates": [
                {
                    "entry_id": candidate.entry_id,
                    "reference_question": candidate.question,
                    "official_answer": candidate.answer,
                    "similarity_score": candidate.similarity_score,
                }
                for candidate in candidates
            ],
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _require_setting(value: str, name: str) -> None:
        if not value.strip():
            raise OpenAIConfigurationError(
                f"Environment variable '{name}' must be configured."
            )
