"""Opt-in tests use dedicated local infrastructure, never the application's .env."""
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.domain.db.base import Base


@pytest.fixture
async def redis_client():
    url = os.getenv("DELIVERY_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set DELIVERY_TEST_REDIS_URL to an isolated Redis")
    client = Redis.from_url(url, decode_responses=True)
    yield client
    await client.aclose()


@pytest.fixture
def factory():
    url = os.getenv("DELIVERY_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set DELIVERY_TEST_DATABASE_URL to an isolated PostgreSQL")
    schema = "delivery_test_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    engine = engine.execution_options(schema_translate_map={None: schema})
    Base.metadata.create_all(engine)
    yield sessionmaker(engine, expire_on_commit=False)
    engine.dispose()
    with admin.begin() as connection:
        connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    admin.dispose()
