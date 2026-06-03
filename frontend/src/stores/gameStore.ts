/**
 * Game Store (Pinia) v3.1
 * ========================
 * Handles:
 * - State mismatch recovery (force REST refresh)
 * - INTERRUPTED actions (from server restart)
 * - Reclaim control on reconnect
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { wsService, type WSMessage, type SceneUpdateMessage } from '@/services/websocket'
import { gameApi, type CharacterState, type SceneOutput } from '@/services/api'

export interface PendingTask {
  task_id: string
  action_id?: string
  round: number
  option_id: string
  attitude_selections: any[]
  submitted_at: number
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'interrupted'
}

export interface HistoryEntry {
  round: number
  narrative: string
  timestamp: string
  choice_made?: string
  status?: string
}

export const useGameStore = defineStore('game', () => {
  const characterId = ref<string | null>(null)
  const isConnected = ref(false)
  const isReclaiming = ref(false)
  const currentScene = ref<SceneOutput | null>(null)
  const characterState = ref<CharacterState | null>(null)
  const history = ref<HistoryEntry[]>([])
  const remainingSeconds = ref(15 * 60)

  const pendingTasks = ref<Map<string, PendingTask>>(new Map())
  const isProcessing = computed(() => pendingTasks.value.size > 0)
  const lastTaskError = ref<string | null>(null)
  const stateMismatchWarning = ref<{ client: string; server: string } | null>(null)
  const lastActionInterrupted = ref(false)

  const staminaDisplay = computed(() => characterState.value?.physical.stamina_level ?? 'unknown')
  const healthDisplay = computed(() => characterState.value?.physical.health_status ?? 'unknown')
  const moraleDisplay = computed(() => characterState.value?.mental.morale_level ?? 'unknown')

  const isRoundUrgent = computed(() => remainingSeconds.value < 60 && remainingSeconds.value > 0)
  const isRoundExpired = computed(() => remainingSeconds.value === 0)

  async initialize(characterIdParam: string) {
    characterId.value = characterIdParam
    setupWSHandlers()

    await loadStateFromDB(characterIdParam)

    try {
      await wsService.connect(
        characterIdParam,
        async () => {
          // Reclaim on reconnect
          await reclaimControl(characterIdParam)
        },
        // State mismatch handler
        async (clientId, serverId) => {
          console.warn(`[GameStore] State mismatch: client=${clientId}, server=${serverId}`)
          stateMismatchWarning.value = { client: clientId, server: serverId }
          // Force refresh from DB
          await loadStateFromDB(characterIdParam)
        },
      )
      isConnected.value = true
    } catch (e) {
      console.error('[GameStore] WS connect failed:', e)
      isConnected.value = false
    }
  }

  async function loadStateFromDB(characterIdParam: string) {
    try {
      const [state, scene] = await Promise.all([
        gameApi.getCharacter(characterIdParam),
        gameApi.getCurrentScene(characterIdParam),
      ])
      characterState.value = state
      currentScene.value = scene
      console.log('[GameStore] State loaded from DB')
    } catch (e) {
      console.error('[GameStore] Failed to load state from DB:', e)
    }
  }

  async function reclaimControl(characterIdParam: string) {
    if (isReclaiming.value) return
    isReclaiming.value = true
    console.log('[GameStore] Reclaiming control...')
    try {
      await loadStateFromDB(characterIdParam)
      pendingTasks.value.clear()
      lastTaskError.value = null
    } finally {
      isReclaiming.value = false
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
      pendingTasks.value.clear()
    })

    wsService.on('action_accepted', (msg: WSMessage) => {
      const taskId = msg.task_id
      const actionId = msg.action_id
      const serverSceneId = msg.scene_id  // ECHO from server (authoritative)
      const existing = Array.from(pendingTasks.value.values()).find(t => t.task_id.startsWith('temp_'))
      if (existing) {
        const updated: PendingTask = {
          ...existing,
          task_id: taskId,
          action_id: actionId,
          status: 'pending',
        }
        pendingTasks.value.delete(existing.task_id)
        pendingTasks.value.set(taskId, updated)
      }
      console.log(`[GameStore] Action accepted, server scene_id=${serverSceneId}`)
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
        if (status === 'interrupted') {
          // Server restart occurred while this action was in flight
          lastActionInterrupted.value = true
          console.warn('[GameStore] Action was INTERRUPTED by server restart')
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
      if (msg.code === 'state_mismatch') {
        // Handled by onStateMismatch callback in connect()
        return
      }
      lastTaskError.value = msg.message || 'Unknown error'
    })
  }

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

    // NOTE: We no longer send scene_id in payload!
    // Server reads from DB character_states.current_scene_id
    // (Defense against client tampering / replay attacks)
    wsService.send({
      type: 'action_submit',
      round: currentScene.value.round,
      character_id: characterId.value,
      choice: {
        option_id: optionId,
        attitude_selections: attitudeSelections,
      },
    })

    history.value.unshift({
      round: currentScene.value.round,
      narrative: `[你的選擇] ${optionId} (處理中...)`,
      timestamp: new Date().toISOString(),
      choice_made: optionId,
    })
  }

  function clearTaskError() {
    lastTaskError.value = null
  }

  function clearStateMismatch() {
    stateMismatchWarning.value = null
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
    stateMismatchWarning.value = null
    lastActionInterrupted.value = false
  }

  return {
    // State
    characterId,
    isConnected,
    isReclaiming,
    currentScene,
    characterState,
    history,
    remainingSeconds,
    pendingTasks,
    lastTaskError,
    stateMismatchWarning,
    lastActionInterrupted,

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
    clearTaskError,
    clearStateMismatch,
    cleanup,
  }
})
