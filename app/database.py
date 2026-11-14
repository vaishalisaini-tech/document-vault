from google.cloud.sql.connector import Connector, create_async_connector
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

class Base(DeclarativeBase):
    pass

async def build_engine() -> tuple[AsyncEngine, Connector]:
    connector = await create_async_connector()

    async def getconn():
        return await connector.connect_async(
            settings.instance_connection_name,
            "asyncpg",
            user=settings.db_user,
            password=settings.db_pass,
            db=settings.db_name,
        )

    engine = create_async_engine(
        "postgresql+asyncpg://",     # no host/port: the connector supplies connections
        async_creator=getconn,
        pool_size=5,
        max_overflow=2,
        pool_timeout=30,
        pool_recycle=1800,
        pool_pre_ping=True,
    )
    return engine, connector
