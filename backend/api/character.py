"""
Character API Endpoints (v3.7 — demo + DB modes)
"""
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, func

from ..demo_mode import is_demo_mode
from ..scenes_demo import get_demo_character

router = APIRouter()


@router.get("")
async def list_characters() -> list[dict[str, Any]]:
    """Get all characters (without passwords) for player selection."""
    if is_demo_mode():
        return [{
            "character_id": "char_demo_player",
            "name": "Rockseeker 家族嘅探子",
            "starter_id": "char_starter_01",
        }]
    
    try:
        from ..db import get_db_session
        from ..models import CharacterState

        async with get_db_session() as session:
            stmt = select(CharacterState).order_by(CharacterState.created_at.desc())
            result = await session.execute(stmt)
            chars = result.scalars().all()
            return [
                {
                    "character_id": char.character_id,
                    "name": char.name,
                    "starter_id": char.semantic_profile.get("starter_id", "char_starter_01"),
                    "created_at": char.created_at.isoformat() if char.created_at else None
                }
                for char in chars
            ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.get("/{character_id}")
async def get_character(character_id: str, request: Request) -> dict[str, Any]:
    """
    Get a character's current state.
    Demo mode: returns hard-coded character.
    Full mode: queries DB.
    """
    # Demo mode
    if is_demo_mode():
        demo = get_demo_character(character_id)
        if demo:
            return _demo_to_response(demo)
        # Default demo
        demo = get_demo_character("char_demo_player")
        if demo:
            return _demo_to_response(demo)
        raise HTTPException(status_code=404, detail="Demo character not found")

    # Full mode
    try:
        from ..db import get_db_session
        from ..models import CharacterState

        async with get_db_session() as session:
            char = await session.get(CharacterState, character_id)
            if not char:
                # Phase L2-B: fail-loud. Don't fall back to demo data
                # in full mode. Return 404 explicitly.
                raise HTTPException(
                    status_code=404, detail=f"Character {character_id} not found"
                )

            # Verify password if set
            stored_pwd = char.semantic_profile.get("password")
            if stored_pwd:
                req_pwd = request.headers.get("X-Character-Password")
                if req_pwd != stored_pwd:
                    raise HTTPException(status_code=401, detail="無存取權限：密碼錯誤")

            return {
                "character_id": char.character_id,
                "name": char.name,
                "world_id": char.world_id,
                "current_scene_id": char.current_scene_id,
                "is_alive": char.is_alive,
                "is_npc_mode": char.is_npc_mode,
                "physical": char.semantic_profile.get("physical", {}),
                "mental": char.semantic_profile.get("mental", {}),
                "attitude": char.semantic_profile.get("attitude", {}),
                "inventory": char.semantic_profile.get("inventory", {}),
                "memories": char.semantic_profile.get("memories", []),
                "relationships": char.semantic_profile.get("relationships", {}),
            }
    except HTTPException:
        # Let HTTP exceptions propagate
        raise
    except Exception as e:
        # Real DB error — surface as 500, no demo fallback
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.post("/")
async def create_character(character_data: dict[str, Any]) -> dict[str, Any]:
    """Create a new character."""
    if is_demo_mode():
        return {"character_id": "char_demo_player", "message": "Demo mode: simulated creation"}

    try:
        from ..db import get_db_session
        from ..models import CharacterState

        async with get_db_session() as session:
            # 1. Check maximum player limit (4 players maximum)
            count_stmt = select(func.count(CharacterState.character_id))
            count_result = await session.execute(count_stmt)
            count = count_result.scalar() or 0
            if count >= 4:
                raise HTTPException(status_code=400, detail="角色已達上限（最多 4 名玩家）。無法創建新角色。")

            # 2. Extract input data
            cid = character_data.get("character_id")
            name = character_data.get("name")
            password = character_data.get("password")
            starter_id = character_data.get("starter_id", "char_starter_01")
            
            # Map world_id safely to DB seed world
            world_id = "dnd_5e_forgotten_realms_phandalin"
            default_scene_id = "loc_phandalin_town"

            if not cid or not name:
                raise HTTPException(status_code=400, detail="缺少角色 ID 或名稱")

            # 3. Setup semantic profile based on starter
            starter_name = '艾德溫 — 退伍軍人'
            stamina = 'fresh'
            health = 'healthy'
            morale = 'calm'
            items = [
                { "item_id": "精緻口糧 (rations_fine)", "quantity": 2 },
                { "item_id": "強效治療藥水 (healing_potion)", "quantity": 1 }
            ]
            equipment = { 
                "weapon": "精鋼長劍 (Longsword)", 
                "armor": "鎖子甲 (Chain Mail)", 
                "accessory_1": "家族徽章 (Heirloom)" 
            }

            if starter_id == 'char_starter_02':
                starter_name = '莉拉 — 神秘旅人'
                items = [
                    { "item_id": "盜賊工具 (thieves_tools)", "quantity": 1 },
                    { "item_id": "解毒劑 (antitoxin)", "quantity": 1 }
                ]
                equipment = { 
                    "weapon": "精緻短弓 (Shortbow)", 
                    "armor": "皮革護甲 (Leather Armor)", 
                    "accessory_1": "陰影護身符" 
                }
            elif starter_id == 'char_starter_03':
                starter_name = '湯姆 — 年輕學徒'
                items = [
                    { "item_id": "法術書 (spellbook)", "quantity": 1 },
                    { "item_id": "法術卷軸 (scroll_magic)", "quantity": 2 }
                ]
                equipment = { 
                    "weapon": "防護法杖 (Staff of Defense)", 
                    "armor": "法師長袍 (Robe of Mage)", 
                    "accessory_1": "魔法防護戒指" 
                }

            profile = {
                "password": password,
                "starter_id": starter_id,
                "physical": {
                    "stamina_level": stamina,
                    "stamina_context": "精神飽滿",
                    "health_status": health,
                    "active_effects": []
                },
                "mental": {
                    "morale_level": morale,
                    "alertness_level": "focused"
                },
                "attitude": {
                    "caution": "careful",
                    "empathy": "compassionate",
                    "honor": "honest",
                    "curiosity": "curious",
                    "violence": "defensive"
                },
                "inventory": {
                    "items": items,
                    "equipment": equipment
                },
                "memories": [
                    f"你是 {name}，以「{starter_name}」的身分抵達凡達林。",
                    "你暗中攜帶著冒險所必需的行囊，決意查明失落礦坑的命運。"
                ],
                "relationships": {}
            }

            # 4. Save to DB
            new_char = CharacterState(
                character_id=cid,
                name=name,
                world_id=world_id,
                current_scene_id=default_scene_id,
                semantic_profile=profile,
                is_npc_mode=False,
                is_alive=True
            )
            session.add(new_char)
            await session.commit()
            
            return {
                "character_id": cid,
                "name": name,
                "world_id": world_id,
                "message": "Character created successfully in DB"
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.post("/{character_id}/verify")
async def verify_character_password(character_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Verify password for a character."""
    if is_demo_mode():
        return {"ok": True}

    password = payload.get("password")
    try:
        from ..db import get_db_session
        from ..models import CharacterState

        async with get_db_session() as session:
            char = await session.get(CharacterState, character_id)
            if not char:
                raise HTTPException(status_code=404, detail="找不到該角色")

            stored_pwd = char.semantic_profile.get("password")
            if stored_pwd and stored_pwd != password:
                raise HTTPException(status_code=401, detail="密碼錯誤")

            return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {e}")


@router.post("/reset")
async def reset_world() -> dict[str, Any]:
    """Delete all character states, action history, and reset to initial state."""
    if is_demo_mode():
        return {"ok": True, "message": "Demo mode: simulation reset"}

    try:
        from ..db import engine, get_db_session
        from ..models import CharacterState
        from sqlalchemy import text
        
        async with engine.begin() as conn:
            # 清空動作歷史與角色狀態，以及場景NPC狀態
            await conn.execute(text("DELETE FROM action_history"))
            await conn.execute(text("DELETE FROM character_states"))
            await conn.execute(text("DELETE FROM scene_npc_states"))
        
        # 重新種植 Demo 數據
        from ..scenes_demo import DEMO_SCENE, DEMO_STARTER
        from ..models import Scene, World
        async with get_db_session() as session:
            # World
            world_obj = await session.get(World, DEMO_STARTER["world_id"])
            if not world_obj:
                session.add(
                    World(
                        id=DEMO_STARTER["world_id"],
                        name="被遺忘嘅國度 — 凡達林地區",
                        version="D&D_5e_SRD_v5.1.0",
                        config={"yaml_path": "worlds/dnd_5e_forgotten_realms.yaml"},
                        is_active=True,
                    )
                )
            # Scene
            scene_obj = await session.get(Scene, DEMO_SCENE["scene_id"])
            if not scene_obj:
                session.add(
                    Scene(
                        id=DEMO_SCENE["scene_id"],
                        world_id=DEMO_STARTER["world_id"],
                        name="凡達林鎮 (Phandalin Town)",
                        description=DEMO_SCENE["scene_narrative"],
                        location_tag="settlement",
                        environment_tags=["outdoor", "settlement", "town", "frontier"],
                        active_npcs=[
                            "npc_gundren",
                            "npc_halia",
                            "npc_sister_garaele",
                            "npc_redbrand_ringleader",
                            "npc_injured_traveler_01",
                        ],
                        atmosphere="tense",
                        is_dynamic=False,
                    )
                )
            # Character
            char_obj = await session.get(CharacterState, DEMO_STARTER["character_id"])
            if not char_obj:
                session.add(
                    CharacterState(
                        character_id=DEMO_STARTER["character_id"],
                        name=DEMO_STARTER["name"],
                        world_id=DEMO_STARTER["world_id"],
                        current_scene_id=DEMO_STARTER["current_scene_id"],
                        semantic_profile=DEMO_STARTER["semantic_profile"],
                        is_npc_mode=False,
                        is_alive=True,
                    )
                )
        return {"ok": True, "message": "World reset and demo data re-seeded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error during reset: {e}")


@router.put("/{character_id}")
async def update_character(character_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Update a character (equipment change, etc.)."""
    return {
        "character_id": character_id,
        "message": "TODO: Implement character update",
        "updates": updates,
    }


def _demo_to_response(demo: dict[str, Any]) -> dict[str, Any]:
    """Convert demo data to API response format."""
    return {
        "character_id": demo["character_id"],
        "name": demo["name"],
        "world_id": demo["world_id"],
        "current_scene_id": demo["current_scene_id"],
        "is_alive": demo["is_alive"],
        "is_npc_mode": demo["is_npc_mode"],
        **demo["semantic_profile"],
        "mode": "demo",
    }

