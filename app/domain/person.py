"""Defines the Person domain model."""

from datetime import datetime

from pydantic import BaseModel

from app.domain.enum.channels import Channel


class Person(BaseModel):
    """Represents a contact/user record in the database."""

    id: int | None = None
    phone_number: str
    name: str | None = None
    cpf: str | None = None
    channel: Channel | None = None
    chat_state: str = "START"
    created_at: datetime
