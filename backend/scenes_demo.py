"""
Demo Scene Data
=================
Hard-coded fallback scene content for testing without LLM.
Used when MINIMAX_API_KEY is not set OR LLM call fails.
"""
from typing import Any

# ============================================
# Demo Scene: Phandalin Town (loc_phandalin_town)
# ============================================
DEMO_SCENE: dict[str, Any] = {
    "scene_id": "loc_phandalin_town",
    "scene_narrative": (
        "你從 Old Coast Road 嘅塵土中行入凡達林。\n\n"
        "鎮上嘅建築大多數係木造，經過 30 年風雨有啲破爛但仲算堅固。"
        "街上嘅居民行路時低著頭，唔敢正視彼此。"
        "遠處有幾個戴紅色頭巾嘅武裝人員巡邏，佢哋嘅視線喺你身上停留咗一秒。\n\n"
        "鎮中央有個細小嘅市集，攤販低聲叫賣，聲音入面有一種難以形容嘅恐懼。"
        "空氣中混住烤麵包嘅香味同金屬嘅鏽味。"
    ),
    "choices": [
        {
            "id": "choice_1",
            "vignette": (
                "你將缺口嘅匕首放低喺吧台，老鐵匠嘅視線停喺上面，"
                "佢粗糙嘅手微微抖咗一下。"
            ),
            "intent_category": "character_growth",
            "lore_source": "npc:npc_tharden_rockseeker",
            "direction_hint": "呢個方向會揭示鐵匠嘅過去 — 可能同戰爭有關",
            "attitude_options": [
                {"dimension": "caution", "level": "careful", "effect": "小心翼翼地試探佢嘅反應"},
                {"dimension": "caution", "level": "bold", "effect": "直接問佢呢把匕首嘅歷史"},
                {"dimension": "empathy", "level": "compassionate", "effect": "先問佢嘅手有冇事"},
            ],
        },
        {
            "id": "choice_2",
            "vignette": (
                "牆上嘅舊地圖釘住但已經褪色，你發現一個你認得嘅城鎮符號，"
                "但佢嘅位置同你記憶中嘅唔同。"
            ),
            "intent_category": "world_exploration",
            "lore_source": "location:loc_phandalin_town",
            "direction_hint": "呢個方向會揭示世界嘅地理變化 — 可能同戰後領土變動有關",
            "attitude_options": [
                {"dimension": "caution", "level": "careful", "effect": "默默記住差異，唔出聲"},
                {"dimension": "curiosity", "level": "eager", "effect": "走向學者，指住地圖問呢個符號"},
            ],
        },
        {
            "id": "choice_3",
            "vignette": (
                "老學者 Elara 收起笑臉，佢嘅眼鏡反光遮住咗眼神，"
                "佢慢慢將你嘅地圖推返畀你，手指喺某個位置敲咗兩下。"
            ),
            "intent_category": "relationship",
            "lore_source": "npc:npc_sister_garaele",
            "direction_hint": "呢個方向會建立同學者嘅信任 — 可能換取佢嘅知識",
            "attitude_options": [
                {"dimension": "empathy", "level": "neutral", "effect": "接過地圖，禮貌道謝"},
                {"dimension": "caution", "level": "bold", "effect": "直接問佢想表達咩"},
                {"dimension": "social", "level": "reserved", "effect": "點頭示意，坐喺佢對面"},
            ],
        },
        {
            "id": "choice_4",
            "vignette": (
                "門口嘅受傷旅人咳嗽一聲，佢嘅斗篷下露出一角閃光，"
                "呢個光同你記憶中嘅某種魔法有著相似嘅頻率。"
            ),
            "intent_category": "mystery_revelation",
            "lore_source": "npc:npc_injured_traveler_01",
            "direction_hint": "呢個方向會揭示一個關於魔法嘅謎團 — 可能同戰後魔法失控有關",
            "attitude_options": [
                {"dimension": "caution", "level": "careful", "effect": "保持距離，觀察佢嘅下一步"},
                {"dimension": "curiosity", "level": "eager", "effect": "走近佢，假裝要幫忙"},
                {"dimension": "curiosity", "level": "reserved", "effect": "同老闆點酒，唔動聲色問旅人嘅事"},
            ],
        },
    ],
    "minor_event": {
        "id": "evt_tavern_chatter_03",
        "description": "吧台後面傳嚟一陣低笑，隨即被壓低。",
        "narrative_impact": "subtle",
    },
}


# ============================================
# Demo Starter Character
# ============================================
DEMO_STARTER: dict[str, Any] = {
    "character_id": "char_demo_player",
    "name": "Rockseeker 家族嘅探子",
    "race": "Dwarf (Shield)",
    "world_id": "dnd_5e_forgotten_realms_phandalin",
    "current_scene_id": "loc_phandalin_town",
    "semantic_profile": {
        "physical": {
            "stamina_level": "fresh",
            "stamina_prompt": "[角色] 精神飽滿，動作敏捷，感官敏銳。",
            "health_status": "healthy",
            "active_effects": ["well_fed", "well_rested"],
        },
        "mental": {
            "morale_level": "calm",
            "morale_prompt": "[角色] 情緒平靜，能夠理性判斷。",
            "alertness_level": "focused",
        },
        "attitude": {
            "caution": "bold",
            "empathy": "compassionate",
            "honor": "honest",
            "curiosity": "curious",
            "violence": "defensive",
        },
        "inventory": {
            "items": [
                {"item_id": "item_leather_armor", "quantity": 1},
                {"item_id": "item_iron_dagger", "quantity": 1},
                {"item_id": "item_dry_rations", "quantity": 3},
                {"item_id": "item_water_skin", "quantity": 1},
            ],
            "equipment": {
                "weapon": "item_iron_dagger",
                "armor": "item_leather_armor",
                "accessory_1": None,
                "accessory_2": None,
            },
            "carrying_weight": "light",
        },
        "memories": [
            "你同 Gundren Rockseeker 有血緣關係",
            "你曾經喺矮人礦坑工作",
            "你收到 Gundren 嘅秘密訊息，話有紅印幫嘅威脅",
        ],
        "relationships": {
            "npc_gundren": "family",
            "npc_halia": "wary",
            "npc_sister_garaele": "friendly",
        },
    },
    "is_npc_mode": False,
    "is_alive": True,
}


def get_demo_scene(scene_id: str) -> dict[str, Any] | None:
    """Get demo scene by ID."""
    if scene_id == "loc_phandalin_town":
        return DEMO_SCENE
    return None


def get_demo_character(character_id: str) -> dict[str, Any] | None:
    """Get demo character by ID."""
    if character_id == "char_demo_player":
        return DEMO_STARTER
    return None


def list_demo_choices() -> list[dict[str, Any]]:
    """List all 4 choices from demo scene."""
    return DEMO_SCENE["choices"]
