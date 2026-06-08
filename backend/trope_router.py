import os
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TropeRouter:
    def __init__(self, json_path: str | None = None) -> None:
        if json_path is None:
            json_path = os.path.join(os.path.dirname(__file__), "tropes.json")
        self.json_path = json_path
        self._tropes: list[dict[str, Any]] = []
        self._load_tropes()

    def _load_tropes(self) -> None:
        try:
            if os.path.exists(self.json_path):
                with open(self.json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._tropes = data.get("tropes", [])
            else:
                logger.warning(f"Trope DB not found at: {self.json_path}")
        except Exception as e:
            logger.error(f"Failed to load tropes.json: {e}")
            self._tropes = []

    def get_trope_by_id(self, trope_id: str) -> dict[str, Any] | None:
        for t in self._tropes:
            if t.get("trope_id") == trope_id:
                return t
        return None

    def find_matching_trope(
        self, scene_type: str, has_other_player_trace: bool, npc_status: str
    ) -> dict[str, Any] | None:
        """
        篩選符合當前場景類型、玩家痕跡與NPC狀態的套路。
        若有多個符合，回傳第一個。若無符合，回傳 None。
        """
        for trope in self._tropes:
            conds = trope.get("trigger_conditions", {})

            # 1. 檢查場景類型
            scene_types = conds.get("scene_types", [])
            if scene_type not in scene_types:
                continue

            # 2. 檢查是否需要其他玩家痕跡
            req_trace = conds.get("requires_other_player_trace", False)
            if req_trace and not has_other_player_trace:
                continue

            # 3. 檢查 NPC 狀態
            npc_cond = conds.get("npc_status", "any")
            if npc_cond == "hostile_or_searching":
                if npc_status not in ("hostile", "searching", "hostile_or_searching"):
                    continue

            return trope
        return None
