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

  // Phase L2-I: removed `remainingSeconds`. The round-system has been
  // retired. Players advance at their own pace (free-for-all), and
  // there is no countdown forcing everyone to wait.

  const pendingTasks = ref<Map<string, PendingTask>>(new Map())
  const isProcessing = computed(() => pendingTasks.value.size > 0)
  const lastTaskError = ref<string | null>(null)
  const stateMismatchWarning = ref<{ client: string; server: string } | null>(null)
  const lastActionInterrupted = ref(false)
  // Phase L2-I/Phase B: a sidebar of recent actions taken by OTHER
  // players in the same scene. The server pushes `other_player_action`
  // messages via WebSocket; we keep the most-recent N.
  const otherPlayerActions = ref<
    Array<{
      id: string
      actor_character_id: string
      actor_name: string
      choice_text: string
      world_event?: string
      world_state_change?: boolean
      timestamp: string
    }>
  >([])
  const OTHER_PLAYER_HISTORY_MAX = 10
  // Phase L2-E hotfix: a top-level error message set when a character
  // fails to load (e.g. 404). The GameView watches this and renders
  // an inline banner instead of leaving the 'handling' spinner on
  // forever.
  const loadError = ref<string | null>(null)

  const staminaDisplay = computed(() => characterState.value?.physical.stamina_level ?? 'unknown')
  const healthDisplay = computed(() => characterState.value?.physical.health_status ?? 'unknown')
  const moraleDisplay = computed(() => characterState.value?.mental.morale_level ?? 'unknown')

  function setCharacterState(state: CharacterState) {
    characterState.value = state
  }

  function setCurrentScene(scene: SceneOutput) {
    currentScene.value = scene
  }

  function setLoadError(message: string | null) {
    loadError.value = message
  }

  async function initialize(characterIdParam: string) {
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
      // Phase L2-I: removed `remainingSeconds.value = 15 * 60` reset
      // (no countdown anymore). The next scene arrives immediately
      // on submit; the player can keep playing at their own pace.
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
      // Phase L2-I: countdown message is no longer used. The server
      // no longer broadcasts a 15-minute timer. This handler is kept
      // as a no-op in case old clients or test fixtures still send
      // a `countdown` message; we just ignore it.
      void msg
    })

    wsService.on('world_event', (msg: WSMessage) => {
      history.value.unshift({
        round: history.value.length + 1,
        narrative: `[世界事件] ${msg.event?.description ?? JSON.stringify(msg)}`,
        timestamp: new Date().toISOString(),
      })
    })

    wsService.on('other_player_action', (msg: WSMessage) => {
      // Phase L2-I/Phase B: a different player in our scene just
      // took an action. Append to the recent-activity feed.
      const id = `${msg.task_id ?? 'tx'}-${msg.actor_character_id ?? '?'}-${Date.now()}`
      otherPlayerActions.value.unshift({
        id,
        actor_character_id: msg.actor_character_id ?? '?',
        actor_name: msg.actor_name ?? msg.actor_character_id ?? '另一位玩家',
        choice_text: msg.choice_text ?? '...',
        world_event: msg.world_event,
        world_state_change: msg.world_state_change,
        timestamp: msg.timestamp ?? new Date().toISOString(),
      })
      if (otherPlayerActions.value.length > OTHER_PLAYER_HISTORY_MAX) {
        otherPlayerActions.value.length = OTHER_PLAYER_HISTORY_MAX
      }
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

    // Phase L2-E: hard safety net. The backend's WS handler sends
    // a scene_update with a server-UUID task_id that DOES NOT match
    // the temp_xxx we just set. Even though our scene_update
    // handler calls pendingTasks.value.clear() (which empties the
    // whole map regardless of task_id), a slow response or a
    // late-arriving message can leave a stale entry that locks
    // the UI on the spinner. We also schedule a 30s hard clear so
    // that even if the backend never responds the player can
    // keep playing. The clear is idempotent.
    setTimeout(() => {
      if (pendingTasks.value.size > 0) {
        console.warn(
          '[gameStore] 30s hard clear — backend never confirmed',
          Array.from(pendingTasks.value.keys()),
        )
        pendingTasks.value.clear()
      }
    }, 30000)
    void tempId  // silence unused-variable warning in some configs

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
    pendingTasks,
    lastTaskError,
    stateMismatchWarning,
    lastActionInterrupted,
    otherPlayerActions,
    loadError,

    // Computed
    staminaDisplay,
    healthDisplay,
    moraleDisplay,
    isProcessing,

    // Actions
    setCharacterState,
    setCurrentScene,
    setLoadError,
    initialize,
    submitChoice,
    clearTaskError,
    clearStateMismatch,
    cleanup,
  }
})
