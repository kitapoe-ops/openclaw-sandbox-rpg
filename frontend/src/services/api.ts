/**
 * REST API Service
 * ===================
 * 對應 backend/api/ 嘅 endpoint
 *
 * 參考：docs/API.md
 */

import axios, { type AxiosInstance } from 'axios'

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
    if (characterId.startsWith('custom_char_')) {
      const stored = localStorage.getItem(`openclaw_char_${characterId}`)
      if (stored) {
        return JSON.parse(stored)
      }
      throw new Error(`LocalStorage character not found: ${characterId}`)
    }
    const res = await client.get(`/api/character/${characterId}`)
    return res.data
  },

  async createCharacter(data: { name: string; world_id: string; starter_id: string }): Promise<{ character_id: string }> {
    const characterId = `custom_char_${Date.now()}`
    
    // Assign starter assets and semantics
    let starterName = '艾德溫 — 退伍軍人'
    let starterDesc = '曾經嘅王國士兵，戰後失去一切。'
    let stamina = 'fresh'
    let health = 'healthy'
    let morale = 'calm'
    let items = [
      { item_id: '精緻口糧 (rations_fine)', quantity: 2 },
      { item_id: '強效治療藥水 (healing_potion)', quantity: 1 }
    ]
    let equipment = { 
      weapon: '精鋼長劍 (Longsword)', 
      armor: '鎖子甲 (Chain Mail)', 
      accessory_1: '家族徽章 (Heirloom)' 
    }

    if (data.starter_id === 'char_starter_02') {
      starterName = '莉拉 — 神秘旅人'
      starterDesc = '無人知佢從邊度嚟。知道好多秘密。'
      items = [
        { item_id: '盜賊工具 (thieves_tools)', quantity: 1 },
        { item_id: '解毒劑 (antitoxin)', quantity: 1 }
      ]
      equipment = { 
        weapon: '精緻短弓 (Shortbow)', 
        armor: '皮革護甲 (Leather Armor)', 
        accessory_1: '陰影護身符' 
      }
    } else if (data.starter_id === 'char_starter_03') {
      starterName = '湯姆 — 年輕學徒'
      starterDesc = '充滿熱誠嘅新手魔法師，滿腦書本知識。'
      items = [
        { item_id: '法術書 (spellbook)', quantity: 1 },
        { item_id: '法術卷軸 (scroll_magic)', quantity: 2 }
      ]
      equipment = { 
        weapon: '防護法杖 (Staff of Defense)', 
        armor: '法師長袍 (Robe of Mage)', 
        accessory_1: '魔法防護戒指' 
      }
    }

    const customState: CharacterState = {
      character_id: characterId,
      name: data.name,
      physical: {
        stamina_level: stamina,
        stamina_context: '精神飽滿',
        health_status: health,
        active_effects: []
      },
      mental: {
        morale_level: morale,
        alertness_level: 'alert'
      },
      attitude: {
        caution: 'careful',
        empathy: 'compassionate',
        honor: 'honest',
        curiosity: 'curious',
        violence: 'defensive'
      },
      inventory: {
        items: items,
        equipment: equipment
      },
      current_location: 'loc_phandalin_town',
      memories: [
        `你是 ${data.name}，以「${starterName}」的身分抵達凡達林。`,
        '你暗中攜帶著冒險所必需的行囊，決意查明失落礦坑的命運。'
      ],
      relationships: {}
    }

    const initialScene: SceneOutput = {
      round: 1,
      character_id: characterId,
      narrative: `你越過漫長的石溪小徑，踏入凡達林小鎮。冷冽的濕風自寶劍山脈迎面吹拂，荒廢多年的石柱與殘破圍牆四散，小鎮處處流露著戰後的淒涼。鎮口插著一塊斑駁的木牌：「凡達林 — 歡迎旅人」，然而下方卻被人以匕首粗暴地刻上暗紅色的字跡：「紅印幫控制此地」。沉睡巨人酒館的簷下，幾名頭戴紅色披風、滿身酒氣的匪徒正按著刀柄，不懷好意地打量著你。空氣中凝聚著一觸即發的殺機，冒險由此揭幕，你該如何踏出第一步？`,
      state_changes: {},
      choices: [
        {
          id: 'choice_1',
          lore_source: 'explore',
          vignette: '壓低兜帽，避開匪徒的目光，快步朝前方熱鬧且相對安全的「石丘旅店」走去。',
          direction_hint: '前往石丘旅店',
          intent_category: 'exploration',
          attitude_options: [
            { dimension: 'caution', level: 'careful', effect: '謹慎規避潛在的直接衝突' }
          ]
        },
        {
          id: 'choice_2',
          lore_source: 'talk',
          vignette: '從容走向沉睡巨人酒館簷下的紅印幫匪徒，大方地向他們問路並探聽鎮長廳的位置。',
          direction_hint: '與紅印幫交談',
          intent_category: 'talk',
          attitude_options: [
            { dimension: 'honor', level: 'flexible', effect: '以言辭博取初步信任與動向' }
          ]
        },
        {
          id: 'choice_3',
          lore_source: 'action',
          vignette: '眼神凌厲直視匪徒，右手暗自按在武器上，大步越過他們直接闖入酒館大堂。',
          direction_hint: '強行突入酒館',
          intent_category: 'action',
          attitude_options: [
            { dimension: 'violence', level: 'balanced', effect: '以強硬氣魄對抗可能的勒索' }
          ]
        },
        {
          id: 'choice_4',
          lore_source: 'creative',
          vignette: '故作體力不支摔倒在酒館外，大聲呼救，藉此測試是否有正直的鎮民敢於挺身相助。',
          direction_hint: '偽裝摔倒測試民風',
          intent_category: 'creative',
          attitude_options: [
            { dimension: 'curiosity', level: 'curious', effect: '以反常行徑暗中審查城鎮的良知' }
          ]
        }
      ]
    }

    localStorage.setItem(`openclaw_char_${characterId}`, JSON.stringify(customState))
    localStorage.setItem(`openclaw_scene_${characterId}`, JSON.stringify(initialScene))
    
    try {
      await client.post('/api/character/', {
        character_id: characterId,
        name: data.name,
        world_id: data.world_id,
        starter_id: data.starter_id
      })
    } catch (e) {
      console.warn('Backend Character post skipped, running in sandbox client-side mode.')
    }

    return { character_id: characterId }
  },

  // Scene
  async getCurrentScene(characterId: string): Promise<SceneOutput> {
    if (characterId.startsWith('custom_char_')) {
      const stored = localStorage.getItem(`openclaw_scene_${characterId}`)
      if (stored) {
        return JSON.parse(stored)
      }
      throw new Error(`LocalStorage scene not found: ${characterId}`)
    }
    const res = await client.get(`/api/scene/${characterId}`)
    return res.data
  },

  async getSceneHistory(characterId: string, limit: number = 20): Promise<{ scenes: any[] }> {
    if (characterId.startsWith('custom_char_')) {
      return { scenes: [] }
    }
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
