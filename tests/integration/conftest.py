import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def hdfs_log_payload() -> str:
    return (
        "2024-01-15 08:22:01 ERROR DataNode: Block blk_1234567890 failed checksum\n"
        "2024-01-15 08:22:02 ERROR DataNode: IOException while reading block\n"
        "2024-01-15 08:22:03 WARN  NameNode: Lost heartbeat from dn-3.example.com\n"
        "2024-01-15 08:22:05 ERROR NameNode: DataNode dn-3 declared dead\n"
    )


def make_chunk(content: str) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = [MagicMock()]
    chunk.choices[0].delta = MagicMock()
    chunk.choices[0].delta.content = content
    return chunk


@asynccontextmanager
async def backend_client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def client_factory():
    return backend_client
