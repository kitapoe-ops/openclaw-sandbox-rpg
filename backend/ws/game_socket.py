"""
WebSocket endpoint for real-time game communication.
"""
from fastapi import WebSocket, WebSocketDisconnect
import json
import logging

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket, character_id: str):
    """
    WebSocket endpoint for a specific character.

    Sends:
    - Scene updates
    - New choices
    - State changes
    - World events
    - Countdown timer updates

    Receives:
    - Player choices
    - Ping/pong

    TODO: Implement full WebSocket logic with Redis pub/sub.
    """
    await websocket.accept()
    logger.info(f"WebSocket connected for character: {character_id}")

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()
            message = json.loads(data)

            # TODO: Process player action
            # For now, just echo back
            await websocket.send_json({
                "type": "echo",
                "character_id": character_id,
                "received": message,
            })

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for character: {character_id}")
    except Exception as e:
        logger.error(f"WebSocket error for {character_id}: {e}")
        await websocket.close()
