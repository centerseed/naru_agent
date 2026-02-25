"""整合測試 fixtures — 使用 Naruvia Neon PostgreSQL。

自動載入專案根目錄的 .env.test（若存在）。

執行方式：
    pytest -m integration

或手動指定：
    TEST_PG_URL=postgresql://... pytest -m integration
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


# ---------------------------------------------------------------------------
# 載入 .env.test
# ---------------------------------------------------------------------------

def _load_env_test() -> None:
    """嘗試從專案根目錄的 .env.test 載入環境變數。"""
    env_file = Path(__file__).parents[2] / ".env.test"
    if not env_file.exists():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        # 手動解析（不依賴 python-dotenv）
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_env_test()


def _get_env(key: str) -> str | None:
    return os.environ.get(key)


# ---------------------------------------------------------------------------
# PostgreSQL 連線解析（支援 URL 或個別參數）
# ---------------------------------------------------------------------------

def _parse_pg_config() -> dict:
    """從 TEST_PG_URL 或個別環境變數解析 PostgreSQL 連線參數。"""
    url = _get_env("TEST_PG_URL")
    if url:
        parsed = urlparse(url)
        query = {}
        if parsed.query:
            for part in parsed.query.split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v
        return {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 5432,
            "dbname": (parsed.path or "/neondb").lstrip("/"),
            "user": parsed.username or "postgres",
            "password": parsed.password or "",
            "sslmode": query.get("sslmode", "prefer"),
        }

    return {
        "host": _get_env("TEST_PG_HOST") or "localhost",
        "port": int(_get_env("TEST_PG_PORT") or "5432"),
        "dbname": _get_env("TEST_PG_DB") or "neondb",
        "user": _get_env("TEST_PG_USER") or "postgres",
        "password": _get_env("TEST_PG_PASSWORD") or "",
        "sslmode": _get_env("TEST_PG_SSLMODE") or "prefer",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def mem0_backend() -> str:
    backend = _get_env("TEST_MEM0_BACKEND")
    if not backend:
        pytest.skip("TEST_MEM0_BACKEND not set; skipping integration tests")
    return backend


@pytest.fixture(scope="session")
def pg_config(mem0_backend: str) -> dict:
    if mem0_backend != "pgvector":
        pytest.skip("pg_config fixture only available for pgvector backend")
    return _parse_pg_config()


@pytest.fixture(scope="session")
def mem0_config(mem0_backend: str, pg_config: dict) -> dict:
    model = _get_env("TEST_LLM_MODEL") or "gemini/gemini-2.5-flash-lite"

    if mem0_backend == "pgvector":
        gemini_api_key = _get_env("GEMINI_API_KEY") or ""

        # mem0 pgvector 的 sslmode 實作有 bug：以空格拼接 URI 導致 dbname 解析錯誤。
        # 改用 connection_string 直接傳完整 URL（含 ?sslmode=require）。
        pg_url = _get_env("TEST_PG_URL") or (
            f"postgresql://{pg_config['user']}:{pg_config['password']}"
            f"@{pg_config['host']}:{pg_config['port']}/{pg_config['dbname']}"
            + ("?sslmode=require" if pg_config.get("sslmode") == "require" else "")
        )
        return {
            "llm": {
                "provider": "litellm",
                "config": {"model": model},
            },
            "embedder": {
                "provider": "gemini",
                "config": {
                    "model": "models/gemini-embedding-001",
                    "api_key": gemini_api_key,
                },
            },
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "connection_string": pg_url,
                    "collection_name": "naru_agent_test_memories",
                    "embedding_model_dims": 768,  # Gemini embedding-001 dims
                },
            },
            "version": "v1.1",
        }

    if mem0_backend == "qdrant":
        qdrant_url = _get_env("TEST_QDRANT_URL") or "http://localhost:6333"
        return {
            "llm": {"provider": "litellm", "config": {"model": model}},
            "vector_store": {
                "provider": "qdrant",
                "config": {"url": qdrant_url},
            },
            "version": "v1.1",
        }

    pytest.skip(f"Unknown TEST_MEM0_BACKEND: {mem0_backend}")


@pytest.fixture(scope="session")
def mem0_client(mem0_config: dict):
    try:
        from mem0 import Memory
    except ImportError:
        pytest.skip("mem0ai not installed")

    return Memory.from_config(mem0_config)


@pytest.fixture(scope="session")
def mem0_manager(mem0_client):
    from naru_agent.memory.mem0_manager import Mem0MemoryManager

    return Mem0MemoryManager(client=mem0_client)


# ---------------------------------------------------------------------------
# 清除測試資料
# 改用直接 SQL DELETE，避免 mem0 的 delete() 觸發 LLM 呼叫造成 hanging。
# scope="session" 在全部測試結束後才清除一次。
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def cleanup_test_data(pg_config):
    """Session 結束後用 SQL 直接清除測試記憶，不觸發 LLM。"""
    yield
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=pg_config["host"],
            port=pg_config["port"],
            dbname=pg_config["dbname"],
            user=pg_config["user"],
            password=pg_config["password"],
            sslmode=pg_config.get("sslmode", "prefer"),
            connect_timeout=10,
        )
        cur = conn.cursor()
        # 刪除所有 test_user_ 開頭的記憶
        cur.execute(
            "DELETE FROM naru_agent_test_memories WHERE payload->>'user_id' LIKE %s",
            ("test_user_%",),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass  # cleanup 失敗不影響測試結果


# ---------------------------------------------------------------------------
# PostgreSQL 直連（psycopg2，用於 DB 層驗證）
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_conn(pg_config: dict):
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")

    conn = psycopg2.connect(
        host=pg_config["host"],
        port=pg_config["port"],
        dbname=pg_config["dbname"],
        user=pg_config["user"],
        password=pg_config["password"],
        sslmode=pg_config.get("sslmode", "prefer"),
        connect_timeout=10,
    )
    yield conn
    conn.close()
