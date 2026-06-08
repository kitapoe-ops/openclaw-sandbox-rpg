import pytest
import asyncio
from unittest.mock import AsyncMock
from backend.trope_router import TropeRouter
from backend.prompt_builder import PromptBuilder
from backend.state_machine import SemanticState, SemanticStateMachine
from backend.api.action_processor import ActionProcessor, InMemoryTurnSystem
from backend.soul_transfer import SemanticSoulTransfer, SoulTransferRecord
from backend.llm_client import MockLLMClient


# ============================================
# 1. Trope Router Tests
# ============================================
def test_trope_router_matching():
    router = TropeRouter()

    # 禍水東引需要 requires_other_player_trace=True
    t1 = router.find_matching_trope(
        scene_type="tavern", has_other_player_trace=False, npc_status="hostile"
    )
    # 不應該匹配到 trope_scapegoat_01 (因為無痕跡)
    assert t1 is None or t1.get("trope_id") != "trope_scapegoat_01"

    # 有痕跡時應該匹配到 scapegoat
    t2 = router.find_matching_trope(
        scene_type="tavern", has_other_player_trace=True, npc_status="hostile"
    )
    assert t2 is not None
    assert t2.get("trope_id") == "trope_scapegoat_01"

    # 路見不平不需要痕跡
    t3 = router.find_matching_trope(
        scene_type="alley", has_other_player_trace=False, npc_status="any"
    )
    assert t3 is not None
    assert t3.get("trope_id") == "trope_encounter_01"


# ============================================
# 2. Prompt Builder Injection Tests
# ============================================
@pytest.mark.asyncio
async def test_prompt_builder_trope_injection():
    # 創建具有 active_threads 的 state
    state = SemanticState(
        character_id="hero",
        tags=[],
        active_threads={
            "trope_scapegoat_01": {
                "status": "Active",
                "escalation_level": 0,
                "seeded_round": 1,
                "meta": {"evade_consequence": "通緝令已發酵"},
            }
        },
    )

    builder = PromptBuilder(memory_palace=None)
    prompt = await builder.build(
        character_id="hero",
        current_state=state,
        action_context={"verb": "look", "target": "around"},
    )

    assert "# 故事套路約束" in prompt
    assert "當前作用中套路：【禍水東引 / 背黑鍋】" in prompt
    assert "主角被誤認為是另一個留下痕跡的玩家" in prompt
    assert "通緝令已發酵" not in prompt  # 還沒 Evaded 發酵

    # 模擬 Evaded 且 escalation_level >= 3 的狀態
    state_evaded = SemanticState(
        character_id="hero",
        tags=[],
        active_threads={
            "trope_scapegoat_01": {
                "status": "Evaded",
                "escalation_level": 3,
                "seeded_round": 1,
                "meta": {"evade_consequence": "通緝令已發酵，賞金獵人正在追蹤"},
            }
        },
    )
    prompt_evaded = await builder.build(
        character_id="hero",
        current_state=state_evaded,
        action_context={"verb": "look", "target": "around"},
    )

    assert "偏航後果引爆" in prompt_evaded
    assert "通緝令已發酵，賞金獵人正在追蹤" in prompt_evaded


# ============================================
# 3. Action Processor Escalation Engine Tests
# ============================================
@pytest.mark.asyncio
async def test_action_processor_escalation_engine():
    # 創建狀態機並註冊角色，給定初始 active_threads
    sm = SemanticStateMachine()
    char_state = SemanticState(
        character_id="hero",
        tags=["健康"],
        active_threads={
            "trope_scapegoat_01": {
                "status": "Active",
                "escalation_level": 0,
                "seeded_round": 1,
                "meta": {"evade_consequence": "通緝令已發酵"},
            }
        },
    )
    sm.register(char_state)

    llm = MockLLMClient(canned_response='{"narrative": "OK", "state_mutations": null}')
    proc = ActionProcessor(
        llm_client=llm,
        memory_palace=None,
        turn_system=InMemoryTurnSystem(),
        state_machine=sm,
        prompt_builder=None,
    )

    # 1. 提交不符合要求的動詞 (例如 "look") -> 判定為偏航 (Active -> Evaded, escalation=1)
    await proc.process(character_id="hero", verb="look", target="around")
    updated = sm.get("hero")
    thread = updated.active_threads["trope_scapegoat_01"]
    assert thread["status"] == "Evaded"
    assert thread["escalation_level"] == 1

    # 2. 再次提交不符要求動詞 -> 發酵值累加 (Evaded -> escalation=2)
    await proc.process(character_id="hero", verb="examine", target="wall")
    updated = sm.get("hero")
    thread = updated.active_threads["trope_scapegoat_01"]
    assert thread["status"] == "Evaded"
    assert thread["escalation_level"] == 2

    # 3. 提交符合要求的動詞 (例如 "talk") -> 正面面對衝突，套路完成 (Evaded -> Completed)
    await proc.process(character_id="hero", verb="talk", target="npc")
    updated = sm.get("hero")
    thread = updated.active_threads["trope_scapegoat_01"]
    assert thread["status"] == "Completed"


# ============================================
# 4. Karma Transfer (Soul Transfer) Tests
# ============================================
@pytest.mark.asyncio
async def test_soul_transfer_karma_transfer():
    engine = SemanticSoulTransfer(soul_db_path=":memory:")

    source_threads = {
        "trope_scapegoat_01": {
            "status": "Evaded",
            "escalation_level": 3,
            "seeded_round": 5,
            "meta": {"evade_consequence": "通緝令已發酵"},
        }
    }

    # 執行轉移
    record = await engine.execute_transfer(
        source_character_id="char_dead",
        source_state=["健康"],
        target_vessel_id="vessel_new",
        target_vessel_state=[],
        scene_id="scene_tavern",
        source_active_threads=source_threads,
    )

    # 驗證新產生的 record.carried_threads
    assert record.carried_threads is not None
    assert "trope_scapegoat_01" in record.carried_threads
    carried = record.carried_threads["trope_scapegoat_01"]
    assert carried["status"] == "Evaded"
    assert carried["escalation_level"] == 3
    assert carried["seeded_round"] == 1  # 必須重置為 1
    assert carried["meta"]["evade_consequence"] == "通緝令已發酵"

    # 從 SQLite 重新讀取，確保持久化
    retrieved = await engine.get_transfer(record.transfer_id)
    assert retrieved is not None
    assert retrieved.carried_threads == record.carried_threads

    # 模擬 SQLAlchemy Session 與 CharacterState 對象以測試 apply_transfer 同步
    class MockCharacterState:
        def __init__(self, char_id):
            self.character_id = char_id
            self.active_threads = {}

    class MockSession:
        def __init__(self):
            self.db = {"vessel_new": MockCharacterState("vessel_new")}

        async def get(self, model, pk):
            return self.db.get(pk)

    mock_session = MockSession()

    # 執行套用
    await engine.apply_transfer(record, session=mock_session)

    # 驗證目標 vessel 角色是否成功繼承了 active_threads 因果
    vessel_cs = mock_session.db["vessel_new"]
    assert vessel_cs.active_threads == record.carried_threads
