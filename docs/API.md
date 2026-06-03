# API Reference

> REST API + WebSocket for OpenClaw Sandbox RPG

## Base URL

```
http://localhost:8000
```

## Authentication

> TODO: Implement JWT auth

## REST Endpoints

### Character

#### `GET /api/character/{character_id}`
Get character state.

**Response:**
```json
{
  "character_id": "char_player_01",
  "name": "Edwin",
  "physical": {
    "stamina_level": "fresh",
    "health_status": "healthy",
    "active_effects": []
  },
  "mental": {
    "morale_level": "neutral",
    "alertness_level": "focused"
  },
  "attitude": {
    "caution": "careful"
  },
  "inventory": {
    "items": [...],
    "equipment": {...}
  },
  "current_location": "loc_old_tavern"
}
```

#### `POST /api/character/`
Create new character.

**Request Body:**
```json
{
  "name": "Edwin",
  "world_id": "dnd_5e_forgotten_realms",
  "starter_id": "char_starter_01"
}
```

#### `PUT /api/character/{character_id}`
Update character (equipment change, etc.).

**Request Body:**
```json
{
  "inventory": {
    "equipment": {
      "weapon": "item_iron_dagger"
    }
  }
}
```

### Action

#### `POST /api/action/submit`
Submit a player's choice for current round.

**Request Body:** (follows `player_input.schema.json`)
```json
{
  "round": 5,
  "character_id": "char_player_01",
  "choice": {
    "option_id": "opt_01",
    "attitude_selections": [
      {"dimension": "caution", "level": "careful"}
    ]
  },
  "equipment_change": {
    "weapon": "item_iron_dagger"
  },
  "items_used": []
}
```

**Response:** (follows `scene_output.schema.json`)
```json
{
  "round": 5,
  "narrative": "...",
  "state_changes": {...},
  "choices": [...],
  "minor_event": {...}
}
```

#### `POST /api/action/auto`
Trigger NPC auto-behavior (called when player doesn't submit within 15 min).

**Request Body:**
```json
{
  "character_id": "char_player_01"
}
```

### Scene

#### `GET /api/scene/{character_id}`
Get current scene for a character.

**Response:**
```json
{
  "character_id": "char_player_01",
  "round": 5,
  "narrative": "...",
  "choices": [...],
  "character_state": {...}
}
```

#### `GET /api/scene/{character_id}/history?limit=20`
Get last N scenes.

**Response:**
```json
{
  "character_id": "char_player_01",
  "scenes": [
    {"round": 5, "narrative": "...", "timestamp": "..."},
    ...
  ]
}
```

### World

#### `GET /api/world/{world_id}/state`
Get current world state.

**Response:**
```json
{
  "world_id": "dnd_5e_forgotten_realms",
  "parameters": {
    "hero_power": {"current_level": 1, "max_level": 4},
    ...
  },
  "active_quests": [...],
  "recent_events": [...]
}
```

#### `GET /api/world/{world_id}/parameters`
Get all world parameters and their current levels.

#### `POST /api/world/{world_id}/etl`
Manually trigger daily ETL (admin only).

## WebSocket

### `WS /ws/game/{character_id}`

**Connection:** Per-character persistent connection.

**Server → Client messages:**

```json
{
  "type": "scene_update",
  "round": 5,
  "narrative": "...",
  "choices": [...]
}
```

```json
{
  "type": "state_change",
  "state_changes": {...}
}
```

```json
{
  "type": "countdown",
  "remaining_seconds": 245
}
```

```json
{
  "type": "world_event",
  "event": {...}
}
```

**Client → Server messages:**

```json
{
  "type": "ping"
}
```

```json
{
  "type": "action_submit",
  "player_input": {...}
}
```

## Error Responses

All errors return:
```json
{
  "error": "error_code",
  "message": "Human readable message",
  "details": {}
}
```

### Error Codes

- `400` - Bad Request (invalid schema)
- `401` - Unauthorized
- `403` - Forbidden
- `404` - Not Found
- `422` - Validation Error
- `500` - Internal Server Error
- `503` - LLM Service Unavailable

## Rate Limiting

> TODO: Implement rate limiting

## Pagination

> TODO: Implement pagination for list endpoints

## OpenAPI Docs

Available at `/docs` and `/redoc` when `ENABLE_API_DOCS=true`.
