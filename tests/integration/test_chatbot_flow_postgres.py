import os
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.domain.db.chatbot_flow_model import (
    FlowActionDependencyModel,
    FlowGraphRevisionModel,
    FlowNodeModel,
    FlowTransitionActionModel,
    FlowTransitionModel,
)
from app.domain.enum.chatbot_flow import (
    ChangeEntityType,
    ChangeOperation,
    NodeType,
    RevisionStatus,
)
from app.repository.sql.chatbot_flow_repository import ChatFlowRepository
from app.services.chatbot_flow_admin_service import (
    ChatFlowAdminService,
    DraftChangeInput,
)
from app.services.chatbot_flow_validation_service import ChatFlowValidator


class RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def publish(self, revision: int, flow: Any) -> None:
        self.calls.append((revision, len(flow.nodes)))


def database_url() -> str:
    value = os.getenv("FLOW_TEST_DATABASE_URL")
    if not value:
        pytest.skip("FLOW_TEST_DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_seed_draft_publication_and_optional_action_deletion() -> None:
    engine = create_engine(database_url())
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        version, flow = ChatFlowRepository(factory).load()
        validation = ChatFlowValidator().validate(flow)

        assert version == 1
        assert validation.valid, validation.model_dump()
        assert len(flow.nodes) == 70

        patient_area = flow.get("paciente_inicio")
        approach = flow.get("paciente_psico_abordagem")
        profile = flow.get("paciente_psico_perfil")
        birth_date = flow.get("paciente_data_nascimento")
        assert patient_area is not None
        assert approach is not None
        assert profile is not None
        assert birth_date is not None
        area_targets = {transition.expected_value: transition.target for transition in patient_area.transitions}
        assert area_targets["psicoterapia"] == "paciente_psico_abordagem"
        assert {area_targets[value] for value in ("psiquiatria", "nutricao", "clinico geral")} == {"paciente_data_nascimento"}
        assert {transition.target for transition in approach.transitions} == {"paciente_psico_perfil"}
        assert {transition.target for transition in profile.transitions} == {"paciente_data_nascimento"}
        assert {transition.target for transition in birth_date.transitions} == {"paciente_faixa_valor"}
        assert all(action.config is None for transition in birth_date.transitions for action in transition.actions)

        with factory() as session:
            assert session.scalar(select(func.count(FlowTransitionModel.id))) == 157
            assert session.scalar(select(func.count(FlowTransitionActionModel.id))) == 172
            assert session.scalar(select(func.count(FlowActionDependencyModel.id))) == 60
            end = session.scalar(select(FlowNodeModel).where(FlowNodeModel.type == NodeType.END).limit(1))
            published = session.scalar(
                select(FlowGraphRevisionModel).where(
                    FlowGraphRevisionModel.status == RevisionStatus.PUBLISHED,
                    FlowGraphRevisionModel.version == 1,
                )
            )
            assert end is not None
            assert published is not None
            end_id = end.id
            published_id = published.id

        publisher = RecordingPublisher()
        service = ChatFlowAdminService(factory, publisher)
        draft = service.create_draft(published_id)
        service.save_changes(
            draft["id"],
            [
                DraftChangeInput(
                    entity_type=ChangeEntityType.NODE,
                    operation=ChangeOperation.CREATE,
                    draft_entity_id=-1,
                    new_value={
                        "key": "integration_start",
                        "type": "START",
                        "title": "Início de integração",
                        "description": "Nó criado pelo teste de integração.",
                        "message": "Olá",
                        "position": 999,
                    },
                ),
                DraftChangeInput(
                    entity_type=ChangeEntityType.TRANSITION,
                    operation=ChangeOperation.CREATE,
                    draft_entity_id=-2,
                    new_value={
                        "node_id": -1,
                        "input_type": "AUTO",
                        "expected_value": None,
                        "button_label": None,
                        "next_node_id": end_id,
                        "position": 0,
                    },
                ),
                DraftChangeInput(
                    entity_type=ChangeEntityType.TRANSITION_ACTION,
                    operation=ChangeOperation.CREATE,
                    draft_entity_id=-3,
                    new_value={
                        "transition_id": -2,
                        "action_key": "sheets_store_answer",
                        "config": {
                            "config_type": "sheets_store_answer",
                            "tab": "Pacientes",
                            "column": "G",
                        },
                        "is_required": False,
                    },
                ),
            ],
        )

        assert service.validate(draft["id"]).valid
        result = await service.publish(draft["id"])

        assert result == {
            "revision_id": draft["id"],
            "version": 2,
            "status": "PUBLISHED",
        }
        assert publisher.calls == [(2, 71)]

        with factory() as session:
            created = session.scalar(select(FlowNodeModel).where(FlowNodeModel.key == "integration_start"))
            assert created is not None
            created_id = created.id

        second_draft = service.create_draft(draft["id"])
        service.save_changes(
            second_draft["id"],
            [
                DraftChangeInput(
                    entity_type=ChangeEntityType.NODE,
                    operation=ChangeOperation.DELETE,
                    entity_id=created_id,
                )
            ],
        )
        graph = service.get_graph(second_draft["id"])
        assert all(node["id"] != created_id for node in graph["nodes"])
    finally:
        engine.dispose()
