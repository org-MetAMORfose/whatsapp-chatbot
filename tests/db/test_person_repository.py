from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel
from app.repository.person_repository import PersonRepository


@pytest.fixture
def person_repository(
    session_factory: sessionmaker[Session],
) -> PersonRepository:
    return PersonRepository(session_factory)

def test_create(
    person_repository: PersonRepository,
) -> None:
    person = PersonModel(
        phone_number="11111111111",
        name="Arthur",
        cpf="12345678900",
        chat_state="START",
        created_at=datetime.utcnow(),
    )

    created = person_repository.create(person)

    assert created.id is not None
    assert created.phone_number == "11111111111"


def test_get_by_id(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="22222222222")

    found = person_repository.get_by_id(person.id)

    assert found is not None
    assert found.id == person.id
    assert found.phone_number == "22222222222"


def test_get_by_phone_number(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="33333333333", channel=Channel.WHATSAPP)

    found = person_repository.get_by_phone_number_and_channel("33333333333", Channel.WHATSAPP)

    assert found is not None
    assert found.id == person.id


def test_get_by_cpf(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="44444444444", cpf="99999999999")

    found = person_repository.get_by_cpf("99999999999")

    assert found is not None
    assert found.id == person.id


def test_update(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="55555555555", name="Old Name")

    person.name = "New Name"
    updated = person_repository.update(person)

    found = person_repository.get_by_id(person.id)

    assert updated.name == "New Name"
    assert found is not None
    assert found.name == "New Name"


def test_exists_by_phone_number_returns_true(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    make_person(phone_number="66666666666", channel=Channel.WHATSAPP)

    exists = person_repository.exists_by_phone_number_and_channel("66666666666", Channel.WHATSAPP)

    assert exists is True


def test_exists_by_phone_number_returns_false(
    person_repository: PersonRepository,
) -> None:
    exists = person_repository.exists_by_phone_number_and_channel("00000000000", Channel.WHATSAPP)

    assert exists is False


def test_update_chat_state(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="77777777777", chat_state="START")

    person_repository.update_chat_state(person.id, "NEXT_STATE")
    found = person_repository.get_by_id(person.id)

    assert found is not None
    assert found.chat_state == "NEXT_STATE"


def test_get_with_message_history(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
    make_message_history,
) -> None:
    person = make_person(phone_number="88888888888")
    make_message_history(
        person_id=person.id,
        content="first",
        created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    make_message_history(
        person_id=person.id,
        content="second",
        created_at=datetime.utcnow(),
    )

    found = person_repository.get_with_message_history(person.id)

    assert found is not None
    assert len(found.messages) == 2
    assert found.messages[0].content == "first"
    assert found.messages[1].content == "second"


def test_get_full_profile(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
    make_professional,
    make_patient,
    make_message_history,
) -> None:
    person = make_person(phone_number="99999999999")
    make_professional(
        person=person,
        professional_register="A123",
    )
    make_patient(person=person)
    make_message_history(person_id=person.id, content="hello")

    found = person_repository.get_full_profile(person.id)

    assert found is not None
    assert found.professional is not None
    assert found.patient is not None
    assert len(found.messages) == 1
    assert found.messages[0].content == "hello"


def test_get_messages_by_person_id(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
    make_message_history,
) -> None:
    person = make_person(phone_number="10101010101")

    make_message_history(
        person_id=person.id,
        content="first",
        created_at=datetime.utcnow() - timedelta(minutes=2),
    )
    make_message_history(
        person_id=person.id,
        content="second",
        created_at=datetime.utcnow() - timedelta(minutes=1),
    )
    make_message_history(
        person_id=person.id,
        content="third",
        created_at=datetime.utcnow(),
    )

    messages = person_repository.get_messages_by_person_id(person.id)

    assert len(messages) == 3
    assert messages[0].content == "first"
    assert messages[1].content == "second"
    assert messages[2].content == "third"


def test_create_message(
    person_repository: PersonRepository,
    make_person: Callable[..., PersonModel],
) -> None:
    person = make_person(phone_number="12121212121")

    message = MessageHistoryModel(
        person_id=person.id,
        content="hello",
        created_at=datetime.utcnow(),
        image_url=None,
        document_url=None,
        is_from_user=True,
    )

    created = person_repository.create_message(message)

    messages = person_repository.get_messages_by_person_id(person.id)

    assert created.id is not None
    assert created.person_id == person.id
    assert created.content == "hello"
    assert len(messages) == 1
    assert messages[0].id == created.id
    assert messages[0].content == "hello"
