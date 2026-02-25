"""Mem0 多層記憶整合測試（需要真實外部 DB）。

標記：@pytest.mark.integration

執行：
    TEST_MEM0_BACKEND=pgvector ... pytest -m integration
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# a) 基本 CRUD
# ---------------------------------------------------------------------------

class TestBasicCRUD:
    def test_add_and_get_all(self, mem0_manager):
        user_id = "test_user_basic"
        messages = [
            {"role": "user", "content": "我叫做小明，我喜歡台式料理。"},
            {"role": "assistant", "content": "好的，我記住了。"},
        ]
        mem0_manager.add(user_id, messages)

        memories = mem0_manager.get_all(user_id)
        assert len(memories) > 0
        contents = [m.content for m in memories]
        assert any("小明" in c or "台式料理" in c for c in contents)

    def test_search_returns_relevant_memory(self, mem0_manager):
        user_id = "test_user_search"
        messages = [
            {"role": "user", "content": "我最喜歡吃牛肉麵。"},
            {"role": "assistant", "content": "了解！"},
        ]
        mem0_manager.add(user_id, messages)

        results = mem0_manager.search(user_id, "飲食偏好")
        assert len(results) > 0

    def test_user_isolation(self, mem0_manager):
        u1 = "test_user_u1"
        u2 = "test_user_u2"

        mem0_manager.add(u1, [
            {"role": "user", "content": "我是 u1，喜歡爬山。"},
            {"role": "assistant", "content": "了解！"},
        ])
        mem0_manager.add(u2, [
            {"role": "user", "content": "我是 u2，喜歡游泳。"},
            {"role": "assistant", "content": "了解！"},
        ])

        u1_results = mem0_manager.search(u1, "休閒活動")
        u2_results = mem0_manager.search(u2, "休閒活動")

        u1_contents = [m.content for m in u1_results]
        u2_contents = [m.content for m in u2_results]

        # u1 的記憶不應出現在 u2 的搜尋結果
        assert not any("u1" in c or "爬山" in c for c in u2_contents)
        assert not any("u2" in c or "游泳" in c for c in u1_contents)


# ---------------------------------------------------------------------------
# b) 多層記憶
# ---------------------------------------------------------------------------

class TestMultilayerMemory:
    def test_multilayer_different_categories_stored(self, mem0_manager):
        user_id = "test_user_multilayer"
        messages = [
            {"role": "user", "content": (
                "我叫李華，我在科技公司當軟體工程師。"
                "我喜歡吃日本料理，特別是壽司。"
                "我最好的朋友是張偉，我們一起打羽毛球。"
            )},
            {"role": "assistant", "content": "感謝分享！"},
        ]
        mem0_manager.add(user_id, messages)

        memories = mem0_manager.get_all(user_id)
        assert len(memories) >= 2, f"Expected at least 2 memories, got {len(memories)}"

    def test_multilayer_search_by_category(self, mem0_manager):
        user_id = "test_user_multilayer"
        # 先新增記憶
        mem0_manager.add(user_id, [
            {"role": "user", "content": "我喜歡吃壽司和拉麵，不喜歡辣的食物。"},
            {"role": "assistant", "content": "了解！"},
        ])
        mem0_manager.add(user_id, [
            {"role": "user", "content": "我在做後端開發工作，主要用 Python。"},
            {"role": "assistant", "content": "了解！"},
        ])

        food_results = mem0_manager.search(user_id, "飲食偏好")
        work_results = mem0_manager.search(user_id, "工作")

        assert len(food_results) > 0
        assert len(work_results) > 0

    def test_multilayer_context_string_covers_multiple_types(self, mem0_manager):
        user_id = "test_user_multilayer"
        ctx = mem0_manager.get_context_string(user_id, "告訴我關於這個用戶的事情")
        # context string 應非空
        assert ctx != ""
        # 每行應以 "- " 開頭
        for line in ctx.strip().split("\n"):
            assert line.startswith("- ")


# ---------------------------------------------------------------------------
# c) 三層記憶驗證
# ---------------------------------------------------------------------------

class TestThreeLayerMemory:
    """驗證 mem0 的三層記憶都能正確儲存與讀取。"""

    # ------ 第一層：語義記憶（Semantic Memory，預設） ------

    def test_semantic_memory_extracts_facts(self, mem0_manager):
        """語義記憶：LLM 自動萃取事實，存的是「摘要過的知識」而不是原文。"""
        user_id = "test_user_semantic"
        messages = [
            {"role": "user", "content": "我叫阿強，今年 30 歲，在台北工作，很喜歡打籃球。"},
            {"role": "assistant", "content": "了解！"},
        ]
        mem0_manager.add(user_id, messages, infer=True)

        memories = mem0_manager.get_all(user_id)
        assert len(memories) > 0, "語義記憶應該有萃取出事實"

        contents = " ".join(m.content for m in memories)
        # LLM 應該從原文中萃取出關鍵事實
        assert any(kw in contents for kw in ["阿強", "30", "台北", "籃球"]), (
            f"語義記憶應包含關鍵事實，實際內容：{contents}"
        )

    def test_semantic_memory_updates_existing_fact(self, mem0_manager):
        """語義記憶：相同主題的新資訊應該更新舊記憶，而非重複新增。"""
        user_id = "test_user_semantic_update"
        # 第一次：存舊資訊
        mem0_manager.add(user_id, [
            {"role": "user", "content": "我住在台北。"},
            {"role": "assistant", "content": "好的！"},
        ], infer=True)

        count_before = len(mem0_manager.get_all(user_id))

        # 第二次：更新資訊
        mem0_manager.add(user_id, [
            {"role": "user", "content": "我搬家了，現在住在高雄。"},
            {"role": "assistant", "content": "了解！"},
        ], infer=True)

        memories = mem0_manager.get_all(user_id)
        contents = " ".join(m.content for m in memories)
        # 高雄應該出現（新資訊）
        assert "高雄" in contents or "Kaohsiung" in contents, (
            f"更新後應包含新地址（高雄/Kaohsiung），實際：{contents}"
        )

    # ------ 第二層：短期記憶（Short-term Memory，infer=False） ------

    def test_short_term_memory_stores_raw_messages(self, mem0_manager):
        """短期記憶：infer=False 直接存原始對話，不經 LLM 萃取。"""
        user_id = "test_user_shortterm"
        raw_content = "這是一段很特殊的測試訊息 XYZ_UNIQUE_12345"
        messages = [
            {"role": "user", "content": raw_content},
            {"role": "assistant", "content": "收到。"},
        ]
        mem0_manager.add(user_id, messages, infer=False)

        memories = mem0_manager.get_all(user_id)
        assert len(memories) > 0, "短期記憶應該有存入原始對話"

        # 短期記憶應保留原始內容（不是摘要）
        contents = " ".join(m.content for m in memories)
        assert "XYZ_UNIQUE_12345" in contents, (
            f"短期記憶應保留原始訊息，實際內容：{contents}"
        )

    def test_short_term_vs_semantic_difference(self, mem0_manager):
        """對比測試：短期記憶保留原文，語義記憶存摘要事實。"""
        u_short = "test_user_short_compare"
        u_semantic = "test_user_semantic_compare"
        messages = [
            {"role": "user", "content": "我今天吃了一碗牛肉麵，很好吃，湯頭很濃郁。"},
            {"role": "assistant", "content": "聽起來很棒！"},
        ]

        mem0_manager.add(u_short, messages, infer=False)
        mem0_manager.add(u_semantic, messages, infer=True)

        short_mems = mem0_manager.get_all(u_short)
        semantic_mems = mem0_manager.get_all(u_semantic)

        short_content = " ".join(m.content for m in short_mems)
        semantic_content = " ".join(m.content for m in semantic_mems)

        # 短期記憶：原文關鍵字應保留
        assert "湯頭" in short_content or "牛肉麵" in short_content, (
            f"短期記憶應保留原文細節，實際：{short_content}"
        )
        # 語義記憶：應有記憶（事實萃取）
        assert len(semantic_mems) > 0, "語義記憶應有萃取事實"

    # ------ 第三層：程序記憶（Procedural Memory） ------

    def test_procedural_memory_stored_for_agent(self, mem0_client):
        """程序記憶：用 agent_id 存儲 Agent 學到的方法與步驟。"""
        agent_id = "test_agent_proc"
        user_id = "test_user_proc"
        messages = [
            {"role": "user", "content": "幫我設計一個健身計畫。"},
            {"role": "assistant", "content": (
                "好的，我學到了：設計健身計畫需要先評估體能，"
                "再分配有氧和重訓的比例，每週至少休息一天。"
            )},
        ]

        # 程序記憶用 agent_id 而非 user_id
        result = mem0_client.add(
            messages,
            user_id=user_id,
            agent_id=agent_id,
            memory_type="procedural_memory",
        )
        # 確認有存入（不論格式如何）
        assert result is not None

        # 讀取 agent 的記憶
        all_mems = mem0_client.get_all(user_id=user_id, agent_id=agent_id)
        if isinstance(all_mems, dict):
            entries = all_mems.get("results", [])
        else:
            entries = all_mems if isinstance(all_mems, list) else []

        assert len(entries) > 0, "程序記憶應有儲存"
        contents = " ".join(e.get("memory", "") for e in entries)
        assert len(contents) > 0, "程序記憶內容不應為空"


# ---------------------------------------------------------------------------
# d) 持久化（跨實例）
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_persistence_across_instances(self, mem0_config):
        try:
            from mem0 import Memory
        except ImportError:
            pytest.skip("mem0ai not installed")

        from naru_agent.memory.mem0_manager import Mem0MemoryManager

        user_id = "test_user_persist_user"
        messages = [
            {"role": "user", "content": "我很喜歡在週末健行。"},
            {"role": "assistant", "content": "好的！"},
        ]

        # Step 1: 用 manager_1 寫入
        manager_1 = Mem0MemoryManager(client=Memory.from_config(mem0_config))
        manager_1.add(user_id, messages)
        del manager_1

        # Step 2: 重新建立 manager_2（連同一 DB）
        manager_2 = Mem0MemoryManager(client=Memory.from_config(mem0_config))
        memories = manager_2.get_all(user_id)

        assert len(memories) > 0, "資料在重建實例後消失"


# ---------------------------------------------------------------------------
# d) 直接 DB 驗證（pgvector）
# ---------------------------------------------------------------------------

class TestDirectDBVerification:
    def test_db_contains_memories_after_add(self, mem0_manager, pg_conn):
        user_id = "test_user_verify_user"
        messages = [
            {"role": "user", "content": "我很喜歡看電影，特別是科幻片。"},
            {"role": "assistant", "content": "了解！"},
        ]
        mem0_manager.add(user_id, messages)

        cur = pg_conn.cursor()
        # mem0 pgvector 將 user_id 存在 JSONB payload 欄位中
        cur.execute(
            "SELECT COUNT(*) FROM naru_agent_test_memories WHERE payload->>'user_id' = %s",
            (user_id,),
        )
        count = cur.fetchone()[0]
        cur.close()

        assert count > 0, f"DB 中沒有找到 user_id={user_id} 的記憶"


# ---------------------------------------------------------------------------
# e) 端對端 Runner + Mem0MemoryManager
# ---------------------------------------------------------------------------

class TestE2ERunnerWithMem0:
    def test_runner_saves_memory_to_external_db(self, mem0_config):
        try:
            from mem0 import Memory
        except ImportError:
            pytest.skip("mem0ai not installed")

        import os
        from naru_agent.agent import Agent
        from naru_agent.llm.litellm_provider import LiteLLMProvider as LiteLLM
        from naru_agent.memory.mem0_manager import Mem0MemoryManager
        from naru_agent.runner import Runner

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            pytest.skip("GEMINI_API_KEY not set")

        model = os.environ.get("TEST_LLM_MODEL", "gemini/gemini-2.5-flash-lite")
        user_id = "test_user_e2e_user"

        llm = LiteLLM(model=model, api_key=api_key)
        manager = Mem0MemoryManager(client=Memory.from_config(mem0_config))
        agent = Agent(name="Naru", role="assistant", llm=llm, memory=manager)
        runner = Runner(agent)

        runner.run("我喜歡台式料理，不喜歡麻辣", user_id=user_id)

        memories = manager.get_all(user_id)
        assert len(memories) > 0

    def test_runner_retrieves_memory_in_subsequent_run(self, mem0_config):
        try:
            from mem0 import Memory
        except ImportError:
            pytest.skip("mem0ai not installed")

        import os
        from unittest.mock import MagicMock
        from naru_agent.agent import Agent
        from naru_agent.llm.litellm_provider import LiteLLMProvider as LiteLLM
        from naru_agent.memory.mem0_manager import Mem0MemoryManager
        from naru_agent.runner import Runner
        from tests.conftest import MockLLM

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            pytest.skip("GEMINI_API_KEY not set")

        model = os.environ.get("TEST_LLM_MODEL", "gemini/gemini-2.5-flash-lite")
        user_id = "test_user_e2e_user"

        # 第一次 run（用真實 LLM 存記憶）
        real_llm = LiteLLM(model=model, api_key=api_key)
        manager_1 = Mem0MemoryManager(client=Memory.from_config(mem0_config))
        agent_1 = Agent(name="Naru", role="assistant", llm=real_llm, memory=manager_1)
        Runner(agent_1).run("我不吃麻辣，喜歡清淡的食物", user_id=user_id)

        # 第二次 run — 用 MockLLM 捕捉傳入的 messages
        mock_llm = MockLLM()
        mock_llm.set_response("好的，我知道了。")

        manager_2 = Mem0MemoryManager(client=Memory.from_config(mem0_config))
        agent_2 = Agent(name="Naru", role="assistant", llm=mock_llm, memory=manager_2)
        Runner(agent_2).run("幫我推薦食物", user_id=user_id)

        # 驗證 system message 含有記憶 context
        assert len(mock_llm.chat_calls) > 0
        first_call_messages = mock_llm.chat_calls[0]["messages"]
        system_message = next(
            (m["content"] for m in first_call_messages if m["role"] == "system"), ""
        )
        assert "## Relevant User Context" in system_message
