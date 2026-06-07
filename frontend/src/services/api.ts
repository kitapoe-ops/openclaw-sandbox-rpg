/**
 * REST API Service
 * ===================
 * 對應 backend/api/ 嘅 endpoint
 *
 * 參考：docs/API.md
 */

import axios, { type AxiosInstance } from 'axios'

// Phase L2-H: use window.location.origin as the default so the SPA
// works correctly when served from a Cloudflare tunnel (e.g.
// https://rpg.kitahim.uk) AND from localhost. Without this, axios
// would fall back to http://localhost:8000, which causes a
// "mixed content" error when the page is served over HTTPS.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const client: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ============================================
// Character API
// ============================================

export interface CharacterState {
  character_id: string
  name: string
  physical: {
    stamina_level: string
    stamina_context?: string
    health_status: string
    active_effects: string[]
  }
  mental: {
    morale_level: string
    alertness_level: string
  }
  attitude: Record<string, string>
  inventory: {
    items: Array<{ item_id: string; quantity: number }>
    equipment: Record<string, string | undefined>
  }
  current_location: string
  memories: string[]
  relationships: Record<string, string>
}

export interface SceneOutput {
  round: number
  character_id: string
  narrative: string
  state_changes: any
  choices: Array<{
    id: string
    lore_source: string
    vignette: string
    direction_hint: string
    intent_category: string
    attitude_options: Array<{
      dimension: string
      level: string
      effect?: string
    }>
  }>
  minor_event?: any
}

export const gameApi = {
  // Character
  async getCharacter(characterId: string): Promise<CharacterState> {
    const res = await client.get(`/api/character/${characterId}`)
    return res.data
  },

  async createCharacter(data: { name: string; world_id: string; starter_id: string }): Promise<{ character_id: string }> {
    const res = await client.post('/api/character/', data)
    return res.data
  },

  // Scene
  async getCurrentScene(characterId: string): Promise<SceneOutput> {
    const res = await client.get(`/api/scene/${characterId}`)
    return res.data
  },

  async getSceneHistory(characterId: string, limit: number = 20): Promise<{ scenes: any[] }> {
    const res = await client.get(`/api/scene/${characterId}/history`, { params: { limit } })
    return res.data
  },

  // World
  async getWorldState(worldId: string): Promise<any> {
    const res = await client.get(`/api/world/${worldId}/state`)
    return res.data
  },
}

export default client
