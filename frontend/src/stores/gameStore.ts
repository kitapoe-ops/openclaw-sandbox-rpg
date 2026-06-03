/**
 * Game Store (Pinia) v2.0
 * ========================
 * Manages: character state, current scene, history, countdown, pending tasks.
 *
 * Key change: Tracks pending LLM tasks via task_id, so client can show
 * "processing..." and handle reconnects gracefully.
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { wsService, type WSMessage, type SceneUpdateMessage } from '@/services/websocket'

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

export interface PendingTask {
  task_id: string
  round: number
  option_id: string
  attitude_selections: any[]
  submitted_at: number
  status: 'pending' | 'processing' | 'completed' | 'failed'
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
  const remainingSeconds = ref(15 * 60)

  // Pending tasks tracking
  const pendingTasks = ref<Map<string, PendingTask>>(new Map())
  const isProcessing = computed(() => pendingTasks.value.size > 0)
  const lastTaskError = ref<string | null>(null)

  // ============================================
  // Computed
  // ============================================
  const staminaDisplay = computed(() => characterState.value?.physical.stamina_level ?? 'unknown')
  const healthDisplay = computed(() => characterState.value?.physical.health_status ?? 'unknown')
  const moraleDisplay = computed(() => characterState.value?.mental.morale_level ?? 'unknown')

  const isRoundUrgent = computed(() => remainingSeconds.value < 60 && remainingSeconds.value > 0)
  const isRoundExpired = computed(() => remainingSeconds.value === 0)

  // ============================================
  // Actions
  // ============================================

  async initialize(characterIdParam: string) {
    characterId.value = characterIdParam
    setupWSHandlers()

    try {
      await wsService.connect(characterIdParam)
      isConnected.value = true
    } catch (e) {
      console.error('[GameStore] WS connect failed:', e)
      isConnected.value = false
    }
  }

  function setupWSHandlers() {
    wsService.on('scene_update', (msg: WSMessage) => {
      const sceneMsg = msg as SceneUpdateMessage
      currentScene.value = {
        round: sceneMsg.round,
        character_id: sceneMsg.character_id ?? characterId.value!,
        narrative: sceneMsg.narrative,
        state_changes: sceneMsg.state_changes ?? {},
        choices: sceneMsg.choices ?? [],
        minor_event: sceneMsg.minor_event,
      } as SceneOutput
      remainingSeconds.value = 15 * 60
      // Clear all completed tasks when new scene arrives
      pendingTasks.value.clear()
    })

    wsService.on('action_accepted', (msg: WSMessage) => {
      const taskId = msg.task_id
      // Find the most recent pending task without a real task_id and update it
      const existing = Array.from(pendingTasks.value.values()).find(t => t.task_id.startsWith('temp_'))
      if (existing) {
        const updated: PendingTask = { ...existing, task_id: taskId, status: 'pending' }
        pendingTasks.value.delete(existing.task_id)
        pendingTasks.value.set(taskId, updated)
      }
    })

    wsService.on('task_status', (msg: WSMessage) => {
      const taskId = msg.task_id
      const status = msg.status as PendingTask['status']
      const task = pendingTasks.value.get(taskId)
      if (task) {
        task.status = status
        if (status === 'failed') {
          lastTaskError.value = msg.error || 'Unknown error'
        }
      }
    })

    wsService.on('countdown', (msg: WSMessage) => {
      if (typeof msg.remaining_seconds === 'number') {
        remainingSeconds.value = msg.remaining_seconds
      }
    })

    wsService.on('world_event', (msg: WSMessage) => {
      history.value.unshift({
        round: history.value.length + 1,
        narrative: `[世界事件] ${msg.event?.description ?? JSON.stringify(msg)}`,
        timestamp: new Date().toISOString(),
      })
    })

    wsService.on('error', (msg: WSMessage) => {
      console.error('[WS] Server error:', msg)
      lastTaskError.value = msg.message || 'Unknown error'
    })
  }

  /**
   * Submit a player choice (non-blocking).
   * Returns immediately; result will arrive via scene_update.
   */
  function submitChoice(
    optionId: string,
    attitudeSelections: Array<{ dimension: string; level: string }>,
  ) {
    if (!characterId.value || !currentScene.value) return

    const tempId = `temp_${Date.now()}_${Math.random().toString(36).slice(2)}`
    const task: PendingTask = {
      task_id: tempId,
      round: currentScene.value.round,
      option_id: optionId,
      attitude_selections: attitudeSelections,
      submitted_at: Date.now(),
      status: 'pending',
    }
    pendingTasks.value.set(tempId, task)
    lastTaskError.value = null

    const playerInput = {
      round: currentScene.value.round,
      character_id: characterId.value,
      choice: {
        option_id: optionId,
        attitude_selections: attitudeSelections,
      },
    }

    // Register scene update handler for this task
    wsService.submitAction(
      characterId.value,
      playerInput,
      (sceneMsg) => {
        // Handled by main scene_update listener
        // (We could do task-specific handling here if needed)
      },
    )

    // Optimistically add to history
    history.value.unshift({
      round: currentScene.value.round,
      narrative: `[你的選擇] ${optionId} (處理中...)`,
      timestamp: new Date().toISOString(),
      choice_made: optionId,
    })
  }

  function setCharacterState(state: CharacterState) {
    characterState.value = state
  }

  function setCurrentScene(scene: SceneOutput) {
    currentScene.value = scene
  }

  function clearTaskError() {
    lastTaskError.value = null
  }

  function cleanup() {
    wsService.disconnect()
    isConnected.value = false
    characterId.value = null
    currentScene.value = null
    characterState.value = null
    history.value = []
    pendingTasks.value.clear()
    lastTaskError.value = null
  }

  return {
    // State
    characterId,
    isConnected,
    currentScene,
    characterState,
    history,
    remainingSeconds,
    pendingTasks,
    lastTaskError,

    // Computed
    staminaDisplay,
    healthDisplay,
    moraleDisplay,
    isRoundUrgent,
    isRoundExpired,
    isProcessing,

    // Actions
    initialize,
    submitChoice,
    setCharacterState,
    setCurrentScene,
    clearTaskError,
    cleanup,
  }
})
