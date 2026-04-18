import logging

from redis.asyncio import Redis
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
import app.config.settings as config

logger = logging.getLogger(__name__)

def create_redis() -> Redis:
    redis = Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        db=config.REDIS_DB,
        username=config.REDIS_USERNAME,
        password=config.REDIS_PASSWORD,
        decode_responses=True,
    )
    logger.info("Created Redis client with host=%s, port=%d, db=%d", config.REDIS_HOST, config.REDIS_PORT, config.REDIS_DB)

    return redis

def create_db_engine():
    db = create_engine(config.DATABASE_URL)

    safe_url = make_url(config.DATABASE_URL).render_as_string(hide_password=True)
    logger.info("Created database engine with URL=%s", safe_url)

    return db


def create_session_factory(engine):
    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    logger.info("Created SQLAlchemy session factory")
    return session_factory