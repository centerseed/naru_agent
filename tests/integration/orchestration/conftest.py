"""Orchestration integration tests — no external service dependencies.

Override the parent conftest's autouse cleanup_test_data fixture
so orchestration tests run without TEST_MEM0_BACKEND.
"""

import pytest


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data():
    """No-op override — orchestration tests don't use mem0/pgvector."""
    yield
