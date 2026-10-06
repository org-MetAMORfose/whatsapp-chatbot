from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.delivery_model import OutboxModel
from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel
from app.repository.sql.outbox_repository import OutboxRepository


def test_record_accepted_template_updates_outbox_and_history_atomically(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        session.add(
            OutboxModel(
                id="template-event",
                kind="matching.completed",
                payload={},
                status="processing",
                attempts=1,
            )
        )

    repository = OutboxRepository(session_factory)
    item = OutboxModel(id="template-event", kind="matching.completed", payload={}, attempts=1)

    assert repository.record_accepted_whatsapp_template(
        item,
        phone_number="5511988887777",
        content="[template:matching_paciente:pt_BR] conteúdo",
    )

    with session_factory() as session:
        outbox = session.get(OutboxModel, "template-event")
        person = session.scalar(select(PersonModel))
        history = session.scalar(select(MessageHistoryModel))

        assert outbox is not None
        assert outbox.status == "processing"
        assert outbox.locked_until is not None
        assert person is not None
        assert person.phone_number == "5511988887777"
        assert person.channel == Channel.WHATSAPP
        assert history is not None
        assert history.person_id == person.id
        assert history.content == "[template:matching_paciente:pt_BR] conteúdo"
        assert history.is_from_user is False


def test_stale_outbox_attempt_does_not_create_template_history(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session, session.begin():
        session.add(
            OutboxModel(
                id="template-event",
                kind="matching.completed",
                payload={},
                status="processing",
                attempts=2,
            )
        )

    repository = OutboxRepository(session_factory)
    stale_item = OutboxModel(
        id="template-event",
        kind="matching.completed",
        payload={},
        attempts=1,
    )

    assert not repository.record_accepted_whatsapp_template(
        stale_item,
        phone_number="5511988887777",
        content="[template:matching_paciente:pt_BR] conteúdo",
    )

    with session_factory() as session:
        assert session.scalar(select(PersonModel)) is None
        assert session.scalar(select(MessageHistoryModel)) is None
