"""Defines the Person domain model."""

from datetime import datetime

from pydantic import BaseModel

<<<<<<< HEAD
from app.domain.channels import Channel
=======
from app.domain.enum.channels import Channel
>>>>>>> 76c32e8f4fe56fac17f68502b29ed2dcb80f6397


class Person(BaseModel):
    """Represents a contact/user record in the database."""

    id: int | None = None
    phone_number: str
    name: str | None = None
    cpf: str | None = None
    channel: Channel | None = None
    chat_state: str = "START"
    created_at: datetime
