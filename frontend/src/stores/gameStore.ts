/**
 * Game Store (Pinia)
 * ===================
 * 集中管理遊戲狀態：當前場景、角色狀態、歷史日誌、連接狀態
 *
 * 對應 schema：
 * - docs/SCHEMAS/character_state.schema.json
 * - docs/SCHEMAS/scene_output.schema.json
 * - docs/SCHEMAS/player_input.schema.json
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { wsService, type WSMessage } from '@/services/websocket'

// ============================================
// Types
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

export interface Choice {
  id: string
  lore_source: string
  text: string
  intent_category: string
  attitude_options: Array<{
    dimension: string
    level: string
    effect?: string
  }>
}

export interface SceneOutput {
  round: number
  character_id: string
  narrative: string
  state_changes: any
  choices: Choice[]
  minor_event?: any
  physics_lock_violations?: any[]
}

export interface HistoryEntry {
  round: number
  narrative: string
  timestamp: string
  choice_made?: string
}

// ============================================
// Store
// ============================================

export const useGameStore = defineStore('game', () => {
  // ============================================
  // State
  // ============================================
  const characterId = ref<string | null>(null)
  const isConnected = ref(false)
  const currentScene = ref<SceneOutput | null>(null)
  const characterState = ref<CharacterState | null>(null)
  const history = ref<HistoryEntry[]>([])
  const remainingSeconds = ref(15 * 60) // 15 分鐘
  const isAutoActionTriggered = ref(false)

  // ============================================
  // Computed
  // ============================================
  const staminaDisplay = computed(() => {
    return characterState.value?.physical.stamina_level ?? 'unknown'
  })

  const healthDisplay = computed(() => {
    return characterState.value?.physical.health_status ?? 'unknown'
  })

  const moraleDisplay = computed(() => {
    return characterState.value?.mental.morale_level ?? 'unknown'
  })

  const isRoundUrgent = computed(() => remainingSeconds.value < 60)
  const isRoundExpired = computed(() => remainingSeconds.value === 0)

  // ============================================
  // Actions
  // ============================================

  /**
   * 初始化：連接 WebSocket + 載入角色狀態
   */
  async initialize(characterIdParam: string) {
    characterId.value = characterIdParam

    // 設定 WS 訊息處理器
    setupWSHandlers()

    // 連接
    try {
      await wsService.connect(characterIdParam)
      isConnected.value = true
    } catch (e) {
      console.error('[GameStore] WS connect failed:', e)
      isConnected.value = false
    }
  }

  /**
   * 設定 WebSocket 訊息處理器
   */
  function setupWSHandlers() {
    wsService.on('scene_update', (msg: WSMessage) => {
      currentScene.value = msg as unknown as SceneOutput
      // 重置倒計時
      remainingSeconds.value = 15 * 60
    })

    wsService.on('state_change', (msg: WSMessage) => {
      // 部分狀態更新（無需重新載入整個 scene）
      if (characterState.value) {
        // TODO: Apply state_changes to characterState
        console.log('[GameStore] State change:', msg)
      }
    })

    wsService.on('countdown', (msg: WSMessage) => {
      if (typeof msg.remaining_seconds === 'number') {
        remainingSeconds.value = msg.remaining_seconds
      }
    })

    wsService.on('world_event', (msg: WSMessage) => {
      // 記錄到歷史
      history.value.unshift({
        round: history.value.length + 1,
        narrative: `[世界事件] ${msg.event?.description ?? JSON.stringify(msg)}`,
        timestamp: new Date().toISOString(),
      })
    })
  }

  /**
   * 提交玩家選擇
   */
  submitChoice(optionId: string, attitudeSelections: Array<{ dimension: string; level: string }>) {
    if (!characterId.value || !currentScene.value) return

    const playerInput = {
      type: 'action_submit',
      round: currentScene.value.round,
      character_id: characterId.value,
      choice: {
        option_id: optionId,
        attitude_selections: attitudeSelections,
      },
    }

    wsService.send(playerInput)

    // 記錄到歷史
    history.value.unshift({
      round: currentScene.value.round,
      narrative: `[你的選擇] ${optionId}`,
      timestamp: new Date().toISOString(),
      choice_made: optionId,
    })
  }

  /**
   * 設定角色狀態（從 REST API 載入）
   */
  setCharacterState(state: CharacterState) {
    characterState.value = state
  }

  /**
   * 設定當前場景（從 REST API 載入）
   */
  setCurrentScene(scene: SceneOutput) {
    currentScene.value = scene
  }

  /**
   * 清理
   */
  cleanup() {
    wsService.disconnect()
    isConnected.value = false
    characterId.value = null
    currentScene.value = null
    characterState.value = null
    history.value = []
  }

  return {
    // State
    characterId,
    isConnected,
    currentScene,
    characterState,
    history,
    remainingSeconds,
    isAutoActionTriggered,

    // Computed
    staminaDisplay,
    healthDisplay,
    moraleDisplay,
    isRoundUrgent,
    isRoundExpired,

    // Actions
    initialize,
    submitChoice,
    setCharacterState,
    setCurrentScene,
    cleanup,
  }
})
