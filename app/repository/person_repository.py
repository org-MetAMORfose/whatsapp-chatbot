"""Person repository implementation."""

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload, selectinload

from app.domain.db.message_history_model import MessageHistoryModel
from app.domain.db.person_model import PersonModel
from app.domain.enum.channels import Channel


class PersonRepository:
    """Repository for managing Person entities."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create(self, person: PersonModel) -> PersonModel:
        """Persist a new person in the current transaction."""
        with self._session_factory() as session:
            session.add(person)
            session.flush()
            session.commit()
            return person

    def get_by_id(self, person_id: int) -> PersonModel | None:
        """Return a person by id."""
        with self._session_factory() as session:
            return session.get(PersonModel, person_id)

    def get_by_phone_number_and_channel(
        self,
        phone_number: str,
        channel: Channel,
    ) -> PersonModel | None:
        """Return a person by phone number and channel."""
        stmt = select(PersonModel).where(
            PersonModel.phone_number == phone_number,
            PersonModel.channel == channel,
        )

        with self._session_factory() as session:
            return session.scalar(stmt)

    def get_or_create_person(
        self,
        phone_number: str,
        channel: Channel,
        name: str | None = None,
    ) -> PersonModel:
        """Return an existing person or create a new one using phone number and channel."""
        with self._session_factory() as session:
            stmt = select(PersonModel).where(
                PersonModel.phone_number == phone_number,
                PersonModel.channel == channel,
            )
            person = session.scalar(stmt)

            if person is not None:
                return person

            person = PersonModel(
                phone_number=phone_number,
                name=name,
                channel=channel,
                chat_state="START",
                created_at=datetime.utcnow(),
            )
            session.add(person)
            session.flush()
            session.commit()
            return person

    def get_by_cpf(self, cpf: str) -> PersonModel | None:
        """Return a person by CPF."""
        stmt = select(PersonModel).where(PersonModel.cpf == cpf)

        with self._session_factory() as session:
            return session.scalar(stmt)

    def update(self, person: PersonModel) -> PersonModel:
        """Merge and return the managed person instance."""
        with self._session_factory() as session:
            merged_person = session.merge(person)
            session.flush()
            session.commit()
            return merged_person

    def exists_by_phone_number_and_channel(
        self,
        phone_number: str,
        channel: Channel,
    ) -> bool:
        """Check whether a person exists for the given phone number and channel."""
        stmt = (
            select(PersonModel.id)
            .where(
                PersonModel.phone_number == phone_number,
                PersonModel.channel == channel,
            )
            .limit(1)
        )

        with self._session_factory() as session:
            return session.scalar(stmt) is not None

    def update_chat_state(self, person_id: int, chat_state: str) -> None:
        """Update the chat state of an existing person."""
        with self._session_factory() as session:
            person = session.get(PersonModel, person_id)
            if person is not None:
                person.chat_state = chat_state
                session.flush()
                session.commit()

    def get_with_message_history(self, person_id: int) -> PersonModel | None:
        """Return a person with message history eagerly loaded."""
        stmt = (
            select(PersonModel)
            .options(selectinload(PersonModel.messages))
            .where(PersonModel.id == person_id)
        )

        with self._session_factory() as session:
            return session.scalar(stmt)

    def get_full_profile(self, person_id: int) -> PersonModel | None:
        """Return a person with messages, professional, and patient loaded."""
        stmt = (
            select(PersonModel)
            .options(
                selectinload(PersonModel.messages),
                joinedload(PersonModel.professional),
                joinedload(PersonModel.patient),
            )
            .where(PersonModel.id == person_id)
        )

        with self._session_factory() as session:
            return session.scalar(stmt)

    def get_messages_by_person_id(self, person_id: int) -> list[MessageHistoryModel]:
        """Return all messages for a person ordered by creation time and id."""
        stmt = (
            select(MessageHistoryModel)
            .where(MessageHistoryModel.person_id == person_id)
            .order_by(MessageHistoryModel.created_at, MessageHistoryModel.id)
        )

        with self._session_factory() as session:
            return list(session.scalars(stmt).all())

    def create_message(self, message: MessageHistoryModel) -> MessageHistoryModel:
        """Persist a new message in the current transaction."""
        with self._session_factory() as session:
            session.add(message)
            session.flush()
            session.commit()
            return message