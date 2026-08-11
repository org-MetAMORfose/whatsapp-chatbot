"""Add FAQ analytics structures and remove professional status history.

Revision ID: 0005_add_faq_analytics
Revises: 0004_add_patient_request_history
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0005_add_faq_analytics"
down_revision: str | None = "0004_add_patient_request_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


faq_session_outcome = postgresql.ENUM(
    "ACTIVE",
    "SATISFIED",
    "ESCALATED",
    "UNKNOWN",
    name="faq_session_outcome",
    create_type=False,
)
faq_answer_status = postgresql.ENUM(
    "SATISFIED",
    "NOT_FOUND",
    "NOT_SATISFIED",
    name="faq_answer_status",
    create_type=False,
)
professional_status = postgresql.ENUM(
    "REGISTER_PENDING",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "PAYMENT_PENDING",
    "ACTIVE",
    "INACTIVE",
    name="professionalstatus",
    create_type=False,
)


def upgrade() -> None:
    # The history is intentionally discarded: the feature and its enum no longer exist.
    op.execute('DELETE FROM "professional_status_history"')
    op.drop_table("professional_status_history")
    op.execute('DROP TYPE "professionalstatus"')

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "CREATE TYPE faq_session_outcome AS ENUM "
        "('ACTIVE', 'SATISFIED', 'ESCALATED', 'UNKNOWN')"
    )
    op.execute(
        "CREATE TYPE faq_answer_status AS ENUM "
        "('SATISFIED', 'NOT_FOUND', 'NOT_SATISFIED')"
    )

    op.create_table(
        "faq_session",
        sa.Column(
            "id",
            sa.Integer(),
            sa.Identity(),
            primary_key=True,
            comment="Identificador único da sessão de FAQ.",
        ),
        sa.Column(
            "person_id",
            sa.Integer(),
            nullable=False,
            comment="Pessoa que iniciou o fluxo de dúvidas.",
        ),
        sa.Column(
            "outcome",
            faq_session_outcome,
            server_default=sa.text("'ACTIVE'::faq_session_outcome"),
            nullable=False,
            comment="Resultado atual ou final da sessão.",
        ),
        sa.Column(
            "question_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="Quantidade de perguntas feitas durante a sessão.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="Data e hora em que a sessão foi iniciada.",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name="fk_faq_session_person_id_person",
        ),
    )

    op.create_table(
        "faq_knowledge_entry",
        sa.Column(
            "id",
            sa.Integer(),
            sa.Identity(),
            primary_key=True,
            comment="Identificador único da entrada da base de conhecimento.",
        ),
        sa.Column(
            "question",
            sa.Text(),
            nullable=False,
            comment="Pergunta de referência usada para gerar o embedding.",
        ),
        sa.Column(
            "answer",
            sa.Text(),
            nullable=False,
            comment="Resposta oficial associada à pergunta de referência.",
        ),
        sa.Column(
            "embedding",
            VECTOR(),
            nullable=False,
            comment=(
                "Vetor semântico da pergunta; a dimensão depende do modelo informado."
            ),
        ),
        sa.Column(
            "embedding_model",
            sa.String(),
            nullable=False,
            comment="Modelo usado para gerar o embedding e determinar sua dimensão.",
        ),
        sa.Column(
            "deleted_at",
            sa.DateTime(),
            nullable=True,
            comment=(
                "Data do soft delete; entradas preenchidas não devem participar da busca."
            ),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="Data e hora de criação da entrada de conhecimento.",
        ),
    )

    op.create_table(
        "faq_interaction",
        sa.Column(
            "id",
            sa.Integer(),
            sa.Identity(),
            primary_key=True,
            comment="Identificador único da interação de FAQ.",
        ),
        sa.Column(
            "session_id",
            sa.Integer(),
            nullable=False,
            comment="Sessão de FAQ em que a pergunta ocorreu.",
        ),
        sa.Column(
            "question_message_id",
            sa.Integer(),
            nullable=False,
            comment="Mensagem original do usuário que contém o texto da pergunta.",
        ),
        sa.Column(
            "selected_entry_id",
            sa.Integer(),
            nullable=True,
            comment=(
                "Entrada escolhida pelo RAG; nula quando nenhuma resposta for adequada."
            ),
        ),
        sa.Column(
            "question_number",
            sa.Integer(),
            nullable=False,
            comment="Posição ordinal da pergunta dentro da sessão.",
        ),
        sa.Column(
            "answer_status",
            faq_answer_status,
            nullable=True,
            comment="Resultado observado para a resposta desta interação.",
        ),
        sa.Column(
            "similarity_score",
            sa.Float(),
            nullable=True,
            comment="Similaridade da entrada selecionada com a pergunta do usuário.",
        ),
        sa.Column(
            "latency_ms",
            sa.Integer(),
            nullable=True,
            comment="Tempo total de processamento da interação em milissegundos.",
        ),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=True,
            comment="Quantidade de tokens enviados ao modelo de IA.",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=True,
            comment="Quantidade de tokens gerados pelo modelo de IA.",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            comment="Data e hora em que a pergunta foi processada.",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["faq_session.id"],
            name="fk_faq_interaction_session_id_faq_session",
        ),
        sa.ForeignKeyConstraint(
            ["question_message_id"],
            ["message_history.id"],
            name="fk_faq_interaction_question_message_id_message_history",
        ),
        sa.ForeignKeyConstraint(
            ["selected_entry_id"],
            ["faq_knowledge_entry.id"],
            name="fk_faq_interaction_selected_entry_id_faq_knowledge_entry",
        ),
    )


def downgrade() -> None:
    op.drop_table("faq_interaction")
    op.drop_table("faq_knowledge_entry")
    op.drop_table("faq_session")

    op.execute("DROP TYPE faq_answer_status")
    op.execute("DROP TYPE faq_session_outcome")

    # Recreate the removed schema for a coherent downgrade. Deleted history rows
    # cannot be restored by a schema migration.
    op.execute(
        "CREATE TYPE professionalstatus AS ENUM ("
        "'REGISTER_PENDING', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', "
        "'PAYMENT_PENDING', 'ACTIVE', 'INACTIVE')"
    )
    op.create_table(
        "professional_status_history",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("professional_id", sa.Integer(), nullable=False),
        sa.Column(
            "professional_status",
            professional_status,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["professional_id"],
            ["professional.id"],
            name="professional_status_history_professional_id_fkey",
            ondelete="CASCADE",
        ),
    )

    # Keep the vector extension installed: it is database-wide and may be shared.
