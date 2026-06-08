import asyncio
import json
import os
import sys
from pathlib import Path

# Add backend to path so we can import llm_client
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

# Avoid cp950 encode errors in Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from backend.llm_client import get_llm_client


async def generate_batch(client, system_prompt, user_prompt, max_retries=3):
    """Call Local LLM and ensure we get a valid JSON response."""
    import httpx
    for attempt in range(max_retries):
        try:
            payload = {
                "model": "qwen2.5-coder-7b-instruct",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.8,
                "max_tokens": 4000
            }
            async with httpx.AsyncClient(timeout=120.0) as http_client:
                r = await http_client.post("http://127.0.0.1:1234/v1/chat/completions", json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"Local LLM returned status {r.status_code}: {r.text}")
                
            data = r.json()
            response = data["choices"][0]["message"]["content"]
            
            # We extract json from markdown blocks if LLM wraps it.
            clean_resp = response.strip()
            # If there's a think block from Reasoning models, strip it!
            if "</think>" in clean_resp:
                clean_resp = clean_resp.split("</think>")[-1].strip()
                
            if clean_resp.startswith("```"):
                # strip code block markers
                lines = clean_resp.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines[-1].strip() == "```":
                    lines = lines[:-1]
                clean_resp = "\n".join(lines).strip()
            
            # Simple brace finder if there's prose around it
            if not (clean_resp.startswith("[") or clean_resp.startswith("{")):
                start_idx = clean_resp.find("[")
                if start_idx == -1:
                    start_idx = clean_resp.find("{")
                if start_idx != -1:
                    clean_resp = clean_resp[start_idx:]
                end_idx = clean_resp.rfind("]")
                if end_idx == -1:
                    end_idx = clean_resp.rfind("}")
                if end_idx != -1:
                    clean_resp = clean_resp[:end_idx+1]
                    
            parsed = json.loads(clean_resp)
            return parsed
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}. Retrying...")
            await asyncio.sleep(2)
    raise RuntimeError("Failed to generate valid JSON from LLM after multiple attempts.")


async def expand_locations(client, base_data):
    print("=== Phase 1: Expanding Locations ===")
    locations_to_add = [
        # Town locations
        {"id": "loc_townmaster_hall", "name": "鎮長廳 (Townmaster's Hall)", "type": "building", "parent_location": "loc_phandalin_town"},
        {"id": "loc_barthens_provisions", "name": "巴森交易站 (Barthen's Provisions)", "type": "building", "parent_location": "loc_phandalin_town"},
        {"id": "loc_lionshield_coster", "name": "獅盾交易站 (Lionshield Coster)", "type": "building", "parent_location": "loc_phandalin_town"},
        {"id": "loc_shrine_of_luck", "name": "幸運女神神殿 (Shrine of Luck)", "type": "building", "parent_location": "loc_phandalin_town"},
        {"id": "loc_alderleaf_farm", "name": "Alderleaf 農場", "type": "building", "parent_location": "loc_phandalin_town_outskirts"},
        {"id": "loc_miner_exchange", "name": "礦工交易所 (Phandalin Miner's Exchange)", "type": "building", "parent_location": "loc_phandalin_town"},
        # Wilderness dungeons
        {"id": "loc_cragmaw_hideout", "name": "克拉格魔巢穴 (Cragmaw Hideout)", "type": "dungeon", "parent_location": "loc_sword_mountains"},
        {"id": "loc_cragmaw_castle", "name": "克拉格魔城堡 (Cragmaw Castle)", "type": "dungeon", "parent_location": "loc_neverwinter_wood"},
        {"id": "loc_wave_echo_cave_entrance", "name": "波濤迴音洞窟入口 (Wave Echo Cave Entrance)", "type": "dungeon", "parent_location": "loc_sword_mountains"},
        {"id": "loc_wave_echo_cave_mine", "name": "波濤迴音洞窟 - 礦坑區", "type": "dungeon", "parent_location": "loc_wave_echo_cave_entrance"},
        {"id": "loc_wave_echo_cave_temple", "name": "波濤迴音洞窟 - 杜馬松神殿", "type": "dungeon", "parent_location": "loc_wave_echo_cave_entrance"},
        {"id": "loc_thundertree_ruins", "name": "雷樹鎮廢墟 (Ruins of Thundertree)", "type": "wilderness", "parent_location": "loc_neverwinter_wood"},
        {"id": "loc_wyvern_tor", "name": "雙頭龍峰 (Wyvern Tor)", "type": "wilderness", "parent_location": "loc_sword_mountains"},
        {"id": "loc_old_owl_well", "name": "古鴞井 (Old Owl Well)", "type": "wilderness", "parent_location": "loc_sword_mountains"}
    ]
    
    system_prompt = (
        "你是一個 D&D 5e 被遺忘的國度 (Forgotten Realms) 官方規則與凡達林 (Phandalin) 地區設定的專家。\n"
        "請根據提供的 Location 簡短列表，生成詳細的 D&D 設定 JSON 數據。\n"
        "輸出的 JSON 必須是一個 JSON 陣列，每個元素包含以下欄位：\n"
        "- id: 字串，地點ID\n"
        "- name: 字串，繁體中文名稱\n"
        "- type: 字串 (例如 'building', 'wilderness', 'dungeon')\n"
        "- parent_location: 字串，父地點ID\n"
        "- description: 至少 200 字的繁體中文詳細場景描述，包含氣味、光線、視覺細節\n"
        "- safe_zone: 布林值 (是否安全區域)\n"
        "- environment_tags: 字串陣列，例如 [\"indoor\", \"safe_zone\", \"tavern\"]\n"
        "- interactables: 字串陣列，列出該地點可以互動的環境道具或特色 (至少 3 個)\n"
        "- npcs_present: 空的字串陣列 []\n"
        "- atmosphere: 字串，描述氣氛 (例如 'peaceful', 'ominous', 'tense')\n"
        "- ambient_sounds: 字串陣列，環境音響效果 (至少 2 個)\n"
        "請只回傳 JSON 陣列，不包含任何額外的解釋文字或 markdown 包裝。"
    )
    
    # Generate in batches of 5 to avoid token limit and maintain high quality
    batch_size = 5
    generated_locations = []
    for i in range(0, len(locations_to_add), batch_size):
        batch = locations_to_add[i:i+batch_size]
        print(f"  Generating Locations batch {i//batch_size + 1}...")
        user_prompt = f"請生成以下地點的詳細 JSON 數據：\n{json.dumps(batch, ensure_ascii=False, indent=2)}"
        try:
            parsed = await generate_batch(client, system_prompt, user_prompt)
            if isinstance(parsed, list):
                generated_locations.extend(parsed)
                print(f"  Generated {len(parsed)} locations.")
            else:
                print(f"  Warning: Expected list, got {type(parsed)}. Retrying once...")
                parsed = await generate_batch(client, system_prompt, user_prompt)
                if isinstance(parsed, list):
                    generated_locations.extend(parsed)
        except Exception as e:
            print(f"  Error in batch: {e}. Falling back to default structures.")
            # Fallback placeholder to keep running
            for loc in batch:
                generated_locations.append({
                    **loc,
                    "description": f"這是關於 {loc['name']} 的詳細描述。環境幽暗而神祕，符合被遺忘的國度設定。",
                    "safe_zone": False,
                    "environment_tags": ["indoor"],
                    "interactables": ["桌椅", "箱子"],
                    "npcs_present": [],
                    "atmosphere": "neutral",
                    "ambient_sounds": ["風聲"]
                })
                
    base_data["locations"].extend(generated_locations)
    print(f"Total locations now: {len(base_data['locations'])}")


async def expand_npcs(client, base_data):
    print("=== Phase 2: Expanding NPCs ===")
    
    # We will expand about 80 NPCs. Let's define the name and concept templates
    npc_templates = [
        # Crucial Named NPCs
        {"id": "npc_sildar", "name": "Sildar Hallwinter", "race": "Human (Chondathan)", "role": "Grip / Alliance Fighter"},
        {"id": "npc_toblen", "name": "Toblen Stonehill", "race": "Human", "role": "Stonehill Innkeeper"},
        {"id": "npc_trilena", "name": "Trilena Stonehill", "race": "Human", "role": "Innkeeper's wife"},
        {"id": "npc_daran", "name": "Daran Edermath", "race": "Elf (Half-Elf)", "role": "Retired adventurer, Orchard owner"},
        {"id": "npc_harbin", "name": "Harbin Wester", "race": "Human", "role": "Cowardly Townmaster"},
        {"id": "npc_linene", "name": "Linene Graywind", "race": "Human", "role": "Lionshield Coster Manager"},
        {"id": "npc_elmar", "name": "Elmar Barthen", "race": "Human", "role": "Barthen's Provisions Owner"},
        {"id": "npc_qelline", "name": "Qelline Alderleaf", "race": "Halfling (Lightfoot)", "role": "Wise farm owner"},
        {"id": "npc_pip", "name": "Pip Alderleaf", "race": "Halfling (Lightfoot)", "role": "Adventurous kid"},
        {"id": "npc_klarg", "name": "Klarg the Bugbear", "race": "Bugbear", "role": "Goblin ambush leader"},
        {"id": "npc_yeemik", "name": "Yeemik the Goblin", "race": "Goblin", "role": "Ambitious goblin second-in-command"},
        {"id": "npc_droop", "name": "Droop the Goblin", "race": "Goblin", "role": "Bullied goblin slave in Redbrand hideout"},
        {"id": "npc_hamun_kost", "name": "Hamun Kost", "race": "Human (Thay)", "role": "Red Wizard of Thay studying Old Owl Well"},
        {"id": "npc_venomfang", "name": "Venomfang", "race": "Green Dragon", "role": "Young Green Dragon in Thundertree ruins"},
        {"id": "npc_reidoth", "name": "Reidoth the Druid", "race": "Human", "role": "Druid of Emerald Enclave in Thundertree"},
        {"id": "npc_nezznar", "name": "Nezznar the Black Spider", "race": "Elf (Drow)", "role": "The mastermind behind the Wave Echo Cave control"},
        
        # Redbrands grunts (15)
        *[{"id": f"npc_redbrand_grunt_{i}", "name": f"紅印幫惡棍 {i} 號", "race": "Human", "role": "Redbrand bandit extortionist"} for i in range(1, 16)],
        
        # Goblins/Cragmaw grunts (15)
        *[{"id": f"npc_goblin_grunt_{i}", "name": f"克拉格魔哥布林 {i} 號", "race": "Goblin", "role": "Cragmaw tribe goblin raider"} for i in range(1, 16)],
        
        # Phandalin Miners (15)
        *[{"id": f"npc_miner_{i}", "name": f"凡達林礦工 {i} 號", "race": "Dwarf / Human", "role": "Local miner or prospector"} for i in range(1, 16)],
        
        # Town guards and peasants (15)
        *[{"id": f"npc_townsperson_{i}", "name": f"凡達林居民 {i} 號", "race": "Human / Halfling", "role": "Local citizen"} for i in range(1, 16)]
    ]
    
    # Filter out NPCs already defined in npcs
    existing_npc_ids = set(base_data.get("npcs", {}).keys())
    npcs_to_generate = [npc for npc in npc_templates if npc["id"] not in existing_npc_ids]
    
    # Let's map each NPC to their initial location
    location_ids = [loc["id"] for loc in base_data["locations"]]
    
    system_prompt = (
        "你是一個 D&D 5e 被遺忘的國度官方規則與凡達林地區設定專家。\n"
        "請根據提供的 NPC 大綱與角色定位，生成高精度的 JSON 數據。\n"
        "輸出的 JSON 必須是一個 JSON 陣列，每個元素代表一個 NPC，包含以下欄位：\n"
        "- id: 字串，NPC ID\n"
        "- name: 字串，繁體中文名稱 (包含英文原名對應)\n"
        "- race: 字串，種族\n"
        "- description: 至少 150 字的繁體中文角色描述 (外貌、身世、性格特徵、談吐)\n"
        "- location_id: 字串，此 NPC 最初所處的地點 ID (必須是提供的合法地點 ID 之一)\n"
        "- inventory: 字串陣列，NPC 的背包物品列表 (包含武器、防具、金幣、藥水等)\n"
        "- stamina: 字串，體力語意狀態 (從 'fresh', 'slight_breath', 'muscle_ache', 'exhausted', 'collapse' 中選擇)\n"
        "- health: 字串，健康語意狀態 (從 'healthy', 'wounded', 'severely_wounded', 'dying', 'dead' 中選擇)\n"
        "- morale: 字串，士氣語意狀態 (從 'elated', 'calm', 'neutral', 'anxious', 'despair' 中選擇)\n"
        "- memories: 字串陣列，NPC 擁有的關鍵記憶片段，例如其目標、恩怨、所知祕密 (至少 2 個)\n"
        "- attitude: 物件，包含以下態度維度及其描述 (caution, empathy, honor, curiosity, violence)\n"
        "請確保 location_id 嚴格匹配我們所提供的位置列表。\n"
        "請只回傳 JSON 陣列，不要任何 markdown 標記包裝或解釋性文字。"
    )
    
    # Helper to guess location_id based on role to make it narratively sensible
    def guess_location(npc_id, role):
        role_l = role.lower()
        if "inn" in role_l or "wife" in role_l:
            return "loc_stonehill_inn"
        if "redbrand" in role_l:
            return "loc_sleeping_giant_taphouse" if "grunt" in role_l else "loc_tresendar_manor"
        if "goblin" in role_l or "bugbear" in role_l:
            return "loc_cragmaw_hideout"
        if "druid" in role_l or "dragon" in role_l:
            return "loc_thundertree_ruins"
        if "wizard" in role_l or "thay" in role_l:
            return "loc_old_owl_well"
        if "townmaster" in role_l:
            return "loc_townmaster_hall"
        if "lionshield" in role_l:
            return "loc_lionshield_coster"
        if "barthen" in role_l:
            return "loc_barthens_provisions"
        if "miner" in role_l:
            return "loc_miner_exchange"
        if "farm" in role_l:
            return "loc_alderleaf_farm"
        # fallback to phandalin town center
        return "loc_phandalin_town"

    batch_size = 4
    generated_npcs = {}
    for i in range(0, len(npcs_to_generate), batch_size):
        batch = npcs_to_generate[i:i+batch_size]
        print(f"  Generating NPCs batch {i//batch_size + 1}/{(len(npcs_to_generate)-1)//batch_size + 1}...")
        
        # Inject guessed location_ids into the batch payload to help LLM place them correctly
        for npc in batch:
            npc["location_id"] = guess_location(npc["id"], npc["role"])
            
        user_prompt = (
            f"請生成以下 NPC 的詳細 JSON 數據，注意 location_id 必須是可用的位置。\n"
            f"可用位置 ID 列表：{json.dumps(location_ids, ensure_ascii=False)}\n"
            f"NPC 大綱列表：\n{json.dumps(batch, ensure_ascii=False, indent=2)}"
        )
        
        try:
            parsed = await generate_batch(client, system_prompt, user_prompt)
            if isinstance(parsed, list):
                for npc in parsed:
                    generated_npcs[npc["id"]] = npc
                print(f"  Generated {len(parsed)} NPCs in this batch.")
            else:
                print(f"  Warning: Expected list, got {type(parsed)}. Retrying once...")
                parsed = await generate_batch(client, system_prompt, user_prompt)
                if isinstance(parsed, list):
                    for npc in parsed:
                        generated_npcs[npc["id"]] = npc
        except Exception as e:
            print(f"  Error in batch: {e}. Falling back to mock structures.")
            for npc in batch:
                generated_npcs[npc["id"]] = {
                    "id": npc["id"],
                    "name": npc["name"],
                    "race": npc["race"],
                    "description": f"這是關於 {npc['name']} 的詳細背景。他在故事中扮演著重要角色，對冒險者的舉動保持警惕。",
                    "location_id": npc["location_id"],
                    "inventory": ["item_iron_dagger", "item_gold_coins x10"],
                    "stamina": "fresh",
                    "health": "healthy",
                    "morale": "calm",
                    "memories": [f"你是 {npc['name']}", "你熟悉凡達林周圍的地理環境"],
                    "attitude": {
                        "caution": "cautious",
                        "empathy": "neutral",
                        "honor": "honest",
                        "curiosity": "curious",
                        "violence": "defensive"
                    }
                }
                
    if not isinstance(base_data.get("npcs"), dict):
        base_data["npcs"] = {}
    
    # Merge existing ones and new ones
    # Convert base_data["npcs"] if it was a list (ensure it is dict)
    if isinstance(base_data["npcs"], list):
        npc_dict = {}
        for npc in base_data["npcs"]:
            npc_dict[npc["id"]] = npc
        base_data["npcs"] = npc_dict
        
    for npc_id, npc_data in generated_npcs.items():
        base_data["npcs"][npc_id] = npc_data
        
    # Also expand narrative_npc_pool
    base_data["narrative_npc_pool"] = list(base_data["npcs"].keys())
    print(f"Total NPCs in database: {len(base_data['npcs'])}")


async def expand_items(client, base_data):
    print("=== Phase 3: Expanding Items ===")
    
    items_to_add = [
        # Weapons
        {"id": "item_longsword", "name": "精鋼長劍 (Longsword)", "type": "weapon"},
        {"id": "item_shortbow", "name": "精緻短弓 (Shortbow)", "type": "weapon"},
        {"id": "item_arrows_quiver", "name": "箭袋與箭矢x20 (Arrows)", "type": "ammunition"},
        {"id": "item_greatsword", "name": "雙手巨劍 (Greatsword)", "type": "weapon"},
        {"id": "item_staff_of_defense", "name": "防護法杖 (Staff of Defense)", "type": "magic_item"},
        {"id": "item_spider_staff", "name": "蜘蛛法杖 (Spider Staff)", "type": "magic_item"},
        {"id": "item_dragonslayer_sword", "name": "屠龍寶劍 (Dragonslayer)", "type": "magic_item"},
        
        # Armors
        {"id": "item_chain_mail", "name": "鎖子甲 (Chain Mail)", "type": "armor"},
        {"id": "item_shield", "name": "鋼鐵圓盾 (Shield)", "type": "armor"},
        {"id": "item_robe_of_mage", "name": "法師長袍 (Robe of Mage)", "type": "armor"},
        
        # Consumables
        {"id": "item_healing_potion_greater", "name": "強效治療藥水 (Greater Healing Potion)", "type": "potion"},
        {"id": "item_potion_of_invisibility", "name": "隱形藥水 (Potion of Invisibility)", "type": "potion"},
        {"id": "item_antitoxin", "name": "解毒劑 (Antitoxin)", "type": "potion"},
        {"id": "item_rations_fine", "name": "高級旅行口糧 (Fine Rations)", "type": "food"},
        
        # Quest items and misc
        {"id": "item_gundren_map", "name": "Gundren 嘅秘密地圖 (Gundren's Map)", "type": "quest_item"},
        {"id": "item_tresendar_key", "name": "Tresendar 莊園密室鑰匙 (Tresendar Key)", "type": "quest_item"},
        {"id": "item_red_brand_cloak", "name": "紅印幫紅色披風 (Red Cloak)", "type": "clothing"},
        {"id": "item_thieves_tools", "name": "盜賊工具 (Thieves' Tools)", "type": "tool"},
        {"id": "item_spellbook_iarno", "name": "Iarno 嘅法術書 (Iarno's Spellbook)", "type": "magic_item"},
        {"id": "item_carnelian_gems", "name": "紅玉髓寶石x3 (Carnelian Gems)", "type": "valuable"}
    ]
    
    # Filter out existing items
    existing_items = set(base_data.get("items", {}).keys())
    items_to_generate = [it for it in items_to_add if it["id"] not in existing_items]
    
    system_prompt = (
        "你是一個 D&D 5e 被遺忘的國度官方規則與物品設定專家。\n"
        "請根據提供的 Item 大綱，生成詳細的 D&D 設定 JSON 數據。\n"
        "輸出的 JSON 必須是一個 JSON 陣列，每個元素包含以下欄位：\n"
        "- id: 字串，物品ID\n"
        "- name: 字串，繁體中文名稱\n"
        "- type: 字串 (例如 'weapon', 'armor', 'potion', 'quest_item', 'tool', 'valuable')\n"
        "- description: 至少 150 字的繁體中文詳細物品背景故事與外觀描述\n"
        "- rules: 物件，物品的規則屬性。例如如果是武器，包含傷害、屬性；如果是防具，包含 AC；如果是藥水，包含效果。不使用任何具體血量數值，而使用語意階梯。例如：「回復 1 階健康」或「提升體力至 fresh」。\n"
        "請只回傳 JSON 陣列，不要任何 markdown 標記包裝或解釋性文字。"
    )
    
    batch_size = 5
    generated_items = {}
    for i in range(0, len(items_to_generate), batch_size):
        batch = items_to_generate[i:i+batch_size]
        print(f"  Generating Items batch {i//batch_size + 1}...")
        user_prompt = f"請生成以下物品的詳細 JSON 數據：\n{json.dumps(batch, ensure_ascii=False, indent=2)}"
        try:
            parsed = await generate_batch(client, system_prompt, user_prompt)
            if isinstance(parsed, list):
                for it in parsed:
                    generated_items[it["id"]] = it
                print(f"  Generated {len(parsed)} items.")
            else:
                print(f"  Warning: Expected list, got {type(parsed)}. Retrying once...")
                parsed = await generate_batch(client, system_prompt, user_prompt)
                if isinstance(parsed, list):
                    for it in parsed:
                        generated_items[it["id"]] = it
        except Exception as e:
            print(f"  Error in batch: {e}. Falling back to default structures.")
            for it in batch:
                generated_items[it["id"]] = {
                    **it,
                    "description": f"這是 {it['name']}。外觀精美，流傳於費倫大陸，在凡達林礦坑的危機中將派上用場。",
                    "rules": {"effect": "在冒險中發揮關鍵作用。"}
                }
                
    if not isinstance(base_data.get("items"), dict):
        base_data["items"] = {}
        
    if isinstance(base_data["items"], list):
        item_dict = {}
        for it in base_data["items"]:
            item_dict[it["id"]] = it
        base_data["items"] = item_dict
        
    for it_id, it_data in generated_items.items():
        base_data["items"][it_id] = it_data
        
    print(f"Total items in database: {len(base_data['items'])}")


async def expand_quests(client, base_data):
    print("=== Phase 4: Expanding Quests ===")
    
    quests_to_add = [
        {
            "id": "quest_redbrand_menace",
            "name": "剷除紅印幫威脅 (The Redbrand Menace)",
            "description": "凡達林鎮上的紅印幫惡霸橫行霸道，鎮民生活在恐懼之中。你需要潛入 Tresendar 莊園的地牢，剷除他們的領袖 Glasstaff，釋放被囚禁的居民。"
        },
        {
            "id": "quest_emerald_enclave_druid",
            "name": "雷樹鎮的德魯伊 (The Druid of Thundertree)",
            "description": "為了尋找失落礦坑的具體地點，你需要前往雷樹鎮廢墟尋找德魯伊 Reidoth。但那裡盤踞著無數亡靈、植物怪，甚至傳聞有一頭綠龍。"
        },
        {
            "id": "quest_old_owl_well_mystery",
            "name": "古鴞井的亡靈 (Old Owl Well Mystery)",
            "description": "凡達林周圍的亡靈活動增加，源頭似乎指向古鴞井。前往調查那裡是否有邪惡的魔法殘留或死靈法師作祟。"
        },
        {
            "id": "quest_orc_trouble_wyvern_tor",
            "name": "雙頭龍峰的獸人 (Orc Trouble at Wyvern Tor)",
            "description": "鎮長 Harbin Wester 委託你前去解決雙頭龍峰的獸人強盜。這些獸人威脅著東邊貿易路線的安全。"
        },
        {
            "id": "quest_wave_echo_cave_recon",
            "name": "收復波濤迴音洞窟 (Reclaim Wave Echo Cave)",
            "description": "在奪回失落礦坑地圖後，你需要前往波濤迴音洞窟，解救最後的矮人 Nundro，並擊敗幕後黑手 Nezznar（黑蜘蛛），重燃魔法大熔爐。"
        }
    ]
    
    # Filter out existing quests
    existing_quests = set(base_data.get("quests", {}).keys())
    quests_to_generate = [q for q in quests_to_add if q["id"] not in existing_quests]
    
    system_prompt = (
        "你是一個 D&D 5e 劇情任務設定專家。\n"
        "請根據提供的 Quest 大綱，生成詳細的 D&D 設定 JSON 數據。\n"
        "輸出的 JSON 必須是一個 JSON 陣列，每個元素代表一個任務，包含以下欄位：\n"
        "- id: 字串，任務ID\n"
        "- name: 字串，繁體中文名稱\n"
        "- description: 至少 200 字的繁體中文詳細任務背景故事\n"
        "- stages: 物件陣列，定義任務的多個階段，每個階段包含：\n"
        "  - stage_id: 整數 (例如 10, 20, 30)\n"
        "  - description: 繁體中文階段目標描述\n"
        "  - completion_condition: 繁體中文完成條件說明\n"
        "請只回傳 JSON 陣列，不要任何 markdown 標記包裝或解釋性文字。"
    )
    
    batch_size = 3
    generated_quests = {}
    for i in range(0, len(quests_to_generate), batch_size):
        batch = quests_to_generate[i:i+batch_size]
        print(f"  Generating Quests batch {i//batch_size + 1}...")
        user_prompt = f"請生成以下任務的詳細 JSON 數據：\n{json.dumps(batch, ensure_ascii=False, indent=2)}"
        try:
            parsed = await generate_batch(client, system_prompt, user_prompt)
            if isinstance(parsed, list):
                for q in parsed:
                    generated_quests[q["id"]] = q
                print(f"  Generated {len(parsed)} quests.")
            else:
                print(f"  Warning: Expected list, got {type(parsed)}. Retrying once...")
                parsed = await generate_batch(client, system_prompt, user_prompt)
                if isinstance(parsed, list):
                    for q in parsed:
                        generated_quests[q["id"]] = q
        except Exception as e:
            print(f"  Error in batch: {e}. Falling back to default structures.")
            for q in batch:
                generated_quests[q["id"]] = {
                    **q,
                    "stages": [
                        {"stage_id": 10, "description": "調查任務起因", "completion_condition": "獲得線索。"},
                        {"stage_id": 20, "description": "剷除威脅來源", "completion_condition": "解決所有威脅。"}
                    ]
                }
                
    if not isinstance(base_data.get("quests"), dict):
        base_data["quests"] = {}
        
    if isinstance(base_data["quests"], list):
        quest_dict = {}
        for q in base_data["quests"]:
            quest_dict[q["id"]] = q
        base_data["quests"] = quest_dict
        
    for q_id, q_data in generated_quests.items():
        base_data["quests"][q_id] = q_data
        
    print(f"Total quests in database: {len(base_data['quests'])}")


async def polish_description(api_key, text, entity_type="location"):
    """Use MiniMax-M3 to rewrite and polish the description in Traditional Chinese / Cantonese TRPG style."""
    if not api_key:
        return text
    if not text or len(text) < 10:
        return text
        
    system_prompt = (
        "你是一個 D&D 5e 被遺忘的國度 (Forgotten Realms) 與 TRPG 跑團大師。\n"
        "你的任務是將輸入的簡短描述，擴寫並潤色為具有濃厚奇幻跑團色彩、細節豐富（包含視覺、聽覺、嗅覺）的文學描述段落。\n"
        "使用生動的繁體中文（可融入合適的廣東話跑團口語，增加沉浸感），文字要優美、有史詩感與懸疑氣氛。\n"
        "請直接回傳潤色後的純文字段落，不要包含任何 json 標籤、解釋性文字或 markdown 格式。"
    )
    user_prompt = f"請潤色並擴寫以下 {entity_type} 的描述：\n{text}"
    
    import httpx
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "MiniMax-M3",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 1.0
    }
    
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post("https://api.minimax.chat/v1/chat/completions", headers=headers, json=payload)
            if r.status_code == 200:
                data = r.json()
                content = data["choices"][0]["message"]["content"]
                if "</think>" in content:
                    content = content.split("</think>")[-1].strip()
                return content.strip()
            else:
                print(f"  Polish attempt {attempt+1} warning: status {r.status_code}")
        except Exception as e:
            print(f"  Polish attempt {attempt+1} warning: {e}")
            await asyncio.sleep(1)
            
    return text


async def polish_all_entities(api_key, base_data):
    print("=== Phase 5: Polishing All Descriptions via MiniMax-M3 ===")
    if not api_key:
        print("  Warning: No MINIMAX_API_KEY found. Skipping polish phase.")
        return
        
    import time
    sem = asyncio.Semaphore(8) # Allow up to 8 concurrent requests to MiniMax
    
    async def task_with_sem(entity, field, etype):
        async with sem:
            original = entity.get(field, "")
            if original:
                polished = await polish_description(api_key, original, etype)
                entity[field] = polished
                
    tasks = []
    
    # 1. Locations
    for loc in base_data.get("locations", []):
        tasks.append(task_with_sem(loc, "description", "location"))
        
    # 2. NPCs
    for npc in base_data.get("npcs", {}).values():
        tasks.append(task_with_sem(npc, "description", "NPC background"))
        
    # 3. Items
    for it in base_data.get("items", {}).values():
        tasks.append(task_with_sem(it, "description", "item legend"))
        
    # 4. Quests
    for q in base_data.get("quests", {}).values():
        tasks.append(task_with_sem(q, "description", "quest narrative"))
        
    print(f"  Polishing {len(tasks)} descriptions concurrently...")
    start_time = time.time()
    await asyncio.gather(*tasks)
    elapsed = time.time() - start_time
    print(f"  Polishing complete in {elapsed:.2f} seconds.")


async def main():
    json_path = Path("worlds/dnd_5e_forgotten_realms.json")
    if not json_path.exists():
        print(f"Error: {json_path} not found. Please run scripts/convert_world.py first.")
        return
        
    print(f"Reading base world data from {json_path}...")
    with open(json_path, "r", encoding="utf-8") as f:
        base_data = json.load(f)
        
    # Standardize format to dictionaries if needed
    if isinstance(base_data.get("npcs"), list):
        base_data["npcs"] = {npc["id"]: npc for npc in base_data["npcs"]}
    if isinstance(base_data.get("items"), list):
        base_data["items"] = {it["id"]: it for it in base_data["items"]}
    if isinstance(base_data.get("quests"), list):
        base_data["quests"] = {q["id"]: q for q in base_data["quests"]}
    if not isinstance(base_data.get("locations"), list):
        base_data["locations"] = []
        
    try:
        client = get_llm_client()
        print(f"Loaded LLM client: {type(client)}")
        
        # Increase read timeout to 120 seconds to prevent read timeouts on large generations
        import httpx
        if hasattr(client, "_timeout"):
            print("Adjusting client timeout to 120s...")
            client._timeout = httpx.Timeout(120.0, connect=10.0, write=20.0, pool=20.0)
        
        # Parallel-like batching, but linear to be gentle on API and memory
        await expand_locations(client, base_data)
        await expand_npcs(client, base_data)
        await expand_items(client, base_data)
        await expand_quests(client, base_data)
        
        # Polish descriptions using MiniMax-M3 (Hybrid Pipeline)
        api_key = os.environ.get("MINIMAX_API_KEY", "")
        await polish_all_entities(api_key, base_data)
        
        # Write back to JSON
        print(f"Writing expanded world data to {json_path}...")
        
        # Convert dictionaries back to lists for database compatibility if necessary.
        # Actually, let's keep npcs, items, quests as lists in the JSON file
        # because the original YAML has them as lists, and WorldLoreDB.load_from_yaml
        # uses `config.get("npcs", [])` and iterates over lists.
        # Yes! In our load_from_json, it also uses self._load_config_dict which expects lists!
        out_data = {**base_data}
        out_data["npcs"] = list(base_data["npcs"].values())
        out_data["items"] = list(base_data["items"].values())
        out_data["quests"] = list(base_data["quests"].values())
        
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(out_data, f, ensure_ascii=False, indent=2)
            
        print("Expansion finished successfully!")
        
        # Print file metrics
        file_size = json_path.stat().st_size
        print(f"New file size: {file_size / 1024:.2f} KB")
        # Token estimation: about 100 tokens per 400 characters (approx 4 bytes/char for utf-8/ch)
        char_count = len(json.dumps(out_data, ensure_ascii=False))
        print(f"Approximate Character Count (UTF-8): {char_count}")
        print(f"Estimated token volume: ~{char_count // 3.5:.0f} tokens")
        
    except Exception as e:
        print(f"Error during expansion: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
