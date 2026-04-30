"""Defines the Person domain model."""

from datetime import datetime

from pydantic import BaseModel

<<<<<<< HEAD
from app.domain.channels import Channel
=======
<<<<<<< HEAD
from app.domain.channels import Channel
=======
from app.domain.enum.channels import Channel
>>>>>>> 75e177151cc5142c5190729f2a72631679fed99b
>>>>>>> main


class Person(BaseModel):
    """Represents a contact/user record in the database."""

    id: int | None = None
    phone_number: str
    name: str | None = None
    cpf: str | None = None
    channel: Channel | None = None
    chat_state: str = "START"
    created_at: datetime
