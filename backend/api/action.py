"""
Action API endpoints - submit player choices.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any

from ..choice_validator import ChoiceValidator

router = APIRouter()
choice_validator = ChoiceValidator()


@router.post("/submit")
async def submit_action(player_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a player's action for a round.

    Flow:
    1. Validate player input
    2. Apply physics lock
    3. Call Scene Agent for narrative + new 4 choices
    4. Call Sub Agent for state calculations
    5. Update character state
    6. Return scene_output to frontend

    TODO: Implement full flow.
    """
    # Placeholder
    return {
        "message": "TODO: Implement action submission flow",
        "received": player_input,
    }


@router.post("/auto")
async def auto_action(character_id: str) -> Dict[str, Any]:
    """
    Auto-action when player doesn't submit within 15 minutes.
    Character enters NPC auto-behavior mode.

    TODO: Implement NPC auto-behavior generation.
    """
    return {
        "character_id": character_id,
        "message": "TODO: Implement NPC auto-behavior",
    }
