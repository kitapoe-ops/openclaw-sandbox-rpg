-- ============================================
-- OpenClaw Sandbox RPG - Database Schema v3.1
-- ============================================
-- Architecture: scenes + character_states + action_history (no separate tasks)
--
-- Key principles:
-- 1. character_states.current_scene_id is SOURCE OF TRUTH for scene_id
-- 2. action_history is the unified table for tasks + narrative log
-- 3. No in-memory state survives restart; everything must be reconstructable from DB
-- 4. INTERRUPTED status handles FastAPI restart zombie tasks
-- ============================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. worlds (loaded from YAML on startup)
-- ============================================
CREATE TABLE IF NOT EXISTS worlds (
    id              VARCHAR(64) PRIMARY KEY,         -- e.g., "dnd_5e_forgotten_realms"
    name            VARCHAR(255) NOT NULL,
    version         VARCHAR(32) NOT NULL,
    config          JSONB NOT NULL,                  -- Full YAML content
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================
-- 2. scenes (World Lore DB entries — can be dynamic)
-- ============================================
CREATE TABLE IF NOT EXISTS scenes (
    id              VARCHAR(128) PRIMARY KEY,        -- e.g., "loc_old_tavern"
    world_id        VARCHAR(64) NOT NULL REFERENCES worlds(id),
    name            VARCHAR(255) NOT NULL,
    description     TEXT NOT NULL,
    location_tag    VARCHAR(64),                    -- e.g., "tavern", "wilderness"
    environment_tags JSONB NOT NULL DEFAULT '[]'::jsonb,  -- ["indoor", "safe_zone"]
    active_npcs     JSONB NOT NULL DEFAULT '[]'::jsonb,   -- ["npc_blacksmith_01"]
    atmosphere      VARCHAR(32) NOT NULL DEFAULT 'peaceful',  -- peaceful/tense/ominous/chaotic
    is_dynamic      BOOLEAN NOT NULL DEFAULT FALSE, -- true if created by God Agent
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_scenes_world ON scenes(world_id);
CREATE INDEX IF NOT EXISTS idx_scenes_location_tag ON scenes(location_tag);

-- ============================================
-- 3. character_states (Pure semantic state)
-- ============================================
CREATE TABLE IF NOT EXISTS character_states (
    character_id    VARCHAR(64) PRIMARY KEY,        -- e.g., "char_player_01"
    name            VARCHAR(255) NOT NULL,
    world_id        VARCHAR(64) NOT NULL REFERENCES worlds(id),
    current_scene_id VARCHAR(128) NOT NULL REFERENCES scenes(id),  -- SOURCE OF TRUTH for scene_id
    semantic_profile JSONB NOT NULL,                -- Full semantic state (stamina, health, morale, etc.)
    is_npc_mode     BOOLEAN NOT NULL DEFAULT FALSE, -- true when no active player
    is_alive        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_character_states_world ON character_states(world_id);
CREATE INDEX IF NOT EXISTS idx_character_states_scene ON character_states(current_scene_id);
CREATE INDEX IF NOT EXISTS idx_character_states_npc ON character_states(is_npc_mode) WHERE is_npc_mode = TRUE;

-- ============================================
-- 4. action_history (UNIFIED table for tasks + narrative log)
-- ============================================
-- Replaces both: tasks (task tracking) + scene_history (narrative log)
-- Every action_submission creates a row.
-- execution_status tracks: PENDING -> COMPLETED/FAILED/INTERRUPTED
-- INTERRUPTED is set on FastAPI startup if PENDING rows exist (zombie recovery)
-- ============================================
CREATE TYPE execution_status AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED', 'INTERRUPTED');

CREATE TABLE IF NOT EXISTS action_history (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    character_id        VARCHAR(64) NOT NULL REFERENCES character_states(character_id),
    scene_id            VARCHAR(128) NOT NULL REFERENCES scenes(id),  -- Frozen at submit time for audit
    round_number        INTEGER NOT NULL,             -- Game round
    player_choice       JSONB NOT NULL,               -- {option_id, attitude_selections, equipment, items}
    execution_status    execution_status NOT NULL DEFAULT 'PENDING',
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at          TIMESTAMPTZ,                  -- When LLM processing began
    completed_at        TIMESTAMPTZ,                  -- When LLM finished (success or fail)
    llm_narrative_output TEXT,                        -- Generated scene_output.narrative
    llm_choices_output  JSONB,                        -- Generated 4 choices
    llm_state_changes   JSONB,                        -- Generated state_changes
    error_message       TEXT,                         -- If FAILED
    interrupted_reason  TEXT,                         -- If INTERRUPTED (e.g., "fastapi_restart")
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_action_history_char ON action_history(character_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_history_scene ON action_history(scene_id, submitted_at DESC);
CREATE INDEX IF NOT EXISTS idx_action_history_status ON action_history(execution_status) WHERE execution_status IN ('PENDING', 'PROCESSING');
CREATE INDEX IF NOT EXISTS idx_action_history_round ON action_history(character_id, round_number DESC);

-- ============================================
-- 5. world_parameter_states (current world parameter levels)
-- ============================================
CREATE TABLE IF NOT EXISTS world_parameter_states (
    id                  VARCHAR(128) PRIMARY KEY,    -- e.g., "dnd_5e.hero_power"
    world_id            VARCHAR(64) NOT NULL REFERENCES worlds(id),
    parameter_id        VARCHAR(128) NOT NULL,      -- e.g., "hero_power"
    current_level       INTEGER NOT NULL DEFAULT 0, -- 0-4 (5-level semantic gradient)
    last_change_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_change_reason  TEXT,
    daily_change_count  INTEGER NOT NULL DEFAULT 0, -- For ±15% fluctuation monitoring
    UNIQUE(world_id, parameter_id)
);

-- ============================================
-- 6. world_events (God Agent daily ETL output)
-- ============================================
CREATE TABLE IF NOT EXISTS world_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    world_id        VARCHAR(64) NOT NULL REFERENCES worlds(id),
    event_type      VARCHAR(32) NOT NULL,           -- npc_action / world_event / quest_trigger / balancing
    description     TEXT NOT NULL,
    affected_locations JSONB NOT NULL DEFAULT '[]'::jsonb,
    affected_npcs   JSONB NOT NULL DEFAULT '[]'::jsonb,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_world_events_world ON world_events(world_id, occurred_at DESC);

-- ============================================
-- 7. Trigger: auto-update updated_at
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

CREATE TRIGGER update_worlds_updated_at BEFORE UPDATE ON worlds
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scenes_updated_at BEFORE UPDATE ON scenes
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_character_states_updated_at BEFORE UPDATE ON character_states
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 8. View: latest action per character (for reclaim)
-- ============================================
CREATE OR REPLACE VIEW v_latest_action_per_character AS
SELECT DISTINCT ON (character_id)
    character_id,
    id AS action_id,
    round_number,
    execution_status,
    submitted_at,
    completed_at
FROM action_history
ORDER BY character_id, submitted_at DESC;

-- ============================================
-- 9. View: pending + processing (for monitoring)
-- ============================================
CREATE OR REPLACE VIEW v_in_flight_actions AS
SELECT
    id,
    character_id,
    scene_id,
    round_number,
    execution_status,
    submitted_at,
    EXTRACT(EPOCH FROM (NOW() - submitted_at)) AS seconds_in_flight
FROM action_history
WHERE execution_status IN ('PENDING', 'PROCESSING')
ORDER BY submitted_at;

-- ============================================
-- 10. Startup recovery function
-- ============================================
-- Called on FastAPI startup to mark zombie PENDING/PROCESSING tasks as INTERRUPTED
-- ============================================
CREATE OR REPLACE FUNCTION recover_interrupted_actions()
RETURNS INTEGER AS $$
DECLARE
    affected_count INTEGER;
BEGIN
    UPDATE action_history
    SET
        execution_status = 'INTERRUPTED',
        interrupted_reason = 'fastapi_restart',
        completed_at = NOW()
    WHERE execution_status IN ('PENDING', 'PROCESSING');

    GET DIAGNOSTICS affected_count = ROW_COUNT;
    RETURN affected_count;
END;
$$ LANGUAGE 'plpgsql';

-- ============================================
-- Sample data (for development)
-- ============================================
-- Will be loaded from worlds/dnd_5e_forgotten_realms.yaml on startup
