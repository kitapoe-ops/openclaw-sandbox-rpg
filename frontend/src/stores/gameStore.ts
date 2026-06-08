/**
 * Game Store (Pinia) v3.2
 * ========================
 * Handles:
 * - State mismatch recovery (force REST refresh)
 * - INTERRUPTED actions (from server restart)
 * - Reclaim control on reconnect
 * - Custom character OFFLINE sandbox simulator
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

// Offline sandbox story library for Custom Characters
const OFFLINE_SCENES = [
  {
    narrative: `你推開石丘旅店（Stonehill Inn）厚實嘅橡木大門，一股溫暖嘅麥酒與烤羊肉香氣夾雜住壁爐嘅熱力迎面撲黎。吧枱前圍攏住幾位疲憊嘅礦工，老闆 Toblen 正低頭擦拭酒杯。見你走入，佢挑了挑眉：「新面孔？凡達林最近唔太平，紅印幫嘅眼線周圍都係，出入小心點。」二樓隱約傳來推搡與怒罵聲，似乎有幾名喝醉嘅紅印幫流氓喺房門外滋事。`,
    choices: [
      { id: 'opt_inn_1', lore_source: 'talk', vignette: '行去吧枱同老闆 Toblen 打聽 Gundren Rockseeker 探險隊失蹤嘅消息。', direction_hint: '向 Toblen 打聽', intent_category: 'talk', attitude_options: [{ dimension: 'caution', level: 'bold' }] },
      { id: 'opt_inn_2', lore_source: 'action', vignette: '手按劍柄，踩著木樓梯上二樓，準備喝止那幾名正在騷擾房客的紅印幫流氓。', direction_hint: '上樓出頭', intent_category: 'action', attitude_options: [{ dimension: 'violence', level: 'balanced' }] },
      { id: 'opt_inn_3', lore_source: 'explore', vignette: '喺壁爐旁揀個不起眼嘅角落坐低，點一杯熱麥酒，靜靜偷聽隔壁桌冒險者嘅低語。', direction_hint: '在暗處偷聽', intent_category: 'exploration', attitude_options: [{ dimension: 'caution', level: 'careful' }] },
      { id: 'opt_inn_4', lore_source: 'creative', vignette: '喺客棧中央大聲朗誦被遺忘國度嘅英雄史詩，嘗試藉此吸引有正義感嘅盟友注意。', direction_hint: '吟遊詩人演講', intent_category: 'creative', attitude_options: [{ dimension: 'curiosity', level: 'curious' }] }
    ]
  },
  {
    narrative: `你沿著石溪小徑摸索前行，終於搵到克拉格魔巢穴（Cragmaw Hideout）嘅入口。洞口雜草叢生，一股刺鼻嘅腐肉與地精體臭令人作嘔。前方傳來一陣尖利嘅爭吵聲，幾隻哥布林正圍繞住一堆柴火，肆無忌憚地翻查搶奪自矮人車隊嘅鐵礦箱與物資。一條吊橋懸掛在奔騰嘅地下暗河上方，這似乎是通往地底更深處的唯一路徑。`,
    choices: [
      { id: 'opt_cave_1', lore_source: 'explore', vignette: '潛伏在鐘乳石陰影中，拉滿短弓瞄準吊橋旁正在瞌睡的哥布林哨兵。', direction_hint: '暗殺哨兵', intent_category: 'exploration', attitude_options: [{ dimension: 'caution', level: 'careful' }] },
      { id: 'opt_cave_2', lore_source: 'action', vignette: '拔出武器發出戰吼，直接衝向篝火堆，一腳將燒紅的火炭踢向哥布林的眼睛！', direction_hint: '正面突襲', intent_category: 'action', attitude_options: [{ dimension: 'violence', level: 'aggressive' }] },
      { id: 'opt_cave_3', lore_source: 'talk', vignette: '從岩壁後站出，以哥布林俚語大聲宣稱自己是代表「黑蜘蛛」的特使，要求面見 Grol。', direction_hint: '假冒蜘蛛特使', intent_category: 'talk', attitude_options: [{ dimension: 'honor', level: 'deceitful' }] },
      { id: 'opt_cave_4', lore_source: 'creative', vignette: '利用火把引燃地上的乾燥藤蔓，製造出森林大火的幻象，將哥布林嚇出山洞。', direction_hint: '放火退敵', intent_category: 'creative', attitude_options: [{ dimension: 'curiosity', level: 'curious' }] }
    ]
  },
  {
    narrative: `你踏入波濤迴音洞窟（Wave Echo Cave）的杜馬松神殿廢墟，傳說中失落已久的魔法大熔爐（Forge of Spells）就在神殿中央，散發著幽藍、瑰麗的奧術光輝。然而，熔爐上方正漂浮著一隻長滿觸手與巨型獨眼的邪魔——眼魔（Spectator）！而黑蜘蛛 Nezznar 正帶著他的黑暗精靈衛兵站在不遠處，用勝券在握的眼神俯視著你。`,
    choices: [
      { id: 'opt_forge_1', lore_source: 'action', vignette: '爆發全部潛力，避開眼魔的射線，直取 Nezznar 進行生死對決！', direction_hint: '斬首黑蜘蛛', intent_category: 'action', attitude_options: [{ dimension: 'violence', level: 'balanced' }] },
      { id: 'opt_forge_2', lore_source: 'explore', vignette: '貓腰滑向熔爐一側的矮人操控台，試圖輸入殘缺的符文，重新啟用熔爐的古老魔法屏障。', direction_hint: '啟用熔爐屏障', intent_category: 'exploration', attitude_options: [{ dimension: 'caution', level: 'careful' }] },
      { id: 'opt_forge_3', lore_source: 'talk', vignette: '直視 Nezznar，大聲揭露他背叛氏族的陰謀，試圖瓦解他身後黑暗精靈護衛的士氣。', direction_hint: '言辭策反', intent_category: 'talk', attitude_options: [{ dimension: 'empathy', level: 'pragmatic' }] },
      { id: 'opt_forge_4', lore_source: 'creative', vignette: '拿出背包中的強效治療藥水擲向眼魔的眼睛，利用藥水內強大的生命能量中和眼魔的死亡射線！', direction_hint: '生命藥水破敵', intent_category: 'creative', attitude_options: [{ dimension: 'curiosity', level: 'curious' }] }
    ]
  }
]

const RANDOM_LOOT = [
  'item_iron_dagger (鐵匕首)',
  'item_healing_potion_greater (強效治療藥水)',
  'item_red_brand_cloak (紅印幫頭巾)',
  'item_carnelian_gems (紅玉髓寶石)',
  'item_spellbook_iarno (Iarno 嘅法術書)'
]

export const useGameStore = defineStore('game', () => {
  const characterId = ref<string | null>(null)
  const isConnected = ref(false)
  const isReclaiming = ref(false)
  const currentScene = ref<SceneOutput | null>(null)
  const characterState = ref<CharacterState | null>(null)
  const history = ref<HistoryEntry[]>([])

  const pendingTasks = ref<Map<string, PendingTask>>(new Map())
  const isProcessing = computed(() => pendingTasks.value.size > 0)
  const lastTaskError = ref<string | null>(null)
  const stateMismatchWarning = ref<{ client: string; server: string } | null>(null)
  const lastActionInterrupted = ref(false)
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
  const loadError = ref<string | null>(null)
  const clientRound = ref(0)

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

    // Check if running in offline client-side sandbox
    if (characterIdParam.startsWith('custom_char_')) {
      isConnected.value = true // Simulated connection
      console.log('[GameStore] Offline custom character sandbox initialized')
      return
    }

    try {
      await wsService.connect(
        characterIdParam,
        async () => {
          await reclaimControl(characterIdParam)
        },
        async (clientId, serverId) => {
          console.warn(`[GameStore] State mismatch: client=${clientId}, server=${serverId}`)
          stateMismatchWarning.value = { client: clientId, server: serverId }
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
      if (scene && typeof scene.round === 'number') {
        clientRound.value = scene.round
      }
      console.log('[GameStore] State loaded')
    } catch (e) {
      console.error('[GameStore] Failed to load state:', e)
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
      clientRound.value += 1
      currentScene.value = {
        round: sceneMsg.round ?? clientRound.value,
        character_id: sceneMsg.character_id ?? characterId.value!,
        narrative: sceneMsg.narrative,
        state_changes: sceneMsg.state_changes ?? {},
        choices: sceneMsg.choices ?? [],
        minor_event: sceneMsg.minor_event,
      } as SceneOutput
      pendingTasks.value.clear()
    })

    wsService.on('action_accepted', (msg: WSMessage) => {
      const taskId = msg.task_id
      const actionId = msg.action_id
      const serverSceneId = msg.scene_id
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
          pendingTasks.value.delete(taskId)
        }
        if (status === 'interrupted') {
          lastActionInterrupted.value = true
          pendingTasks.value.delete(taskId)
        }
      }
    })

    wsService.on('world_event', (msg: WSMessage) => {
      history.value.unshift({
        round: history.value.length + 1,
        narrative: `[世界事件] ${msg.event?.description ?? JSON.stringify(msg)}`,
        timestamp: new Date().toISOString(),
      })
    })

    wsService.on('other_player_action', (msg: WSMessage) => {
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
        return
      }
      lastTaskError.value = msg.message || 'Unknown error'
      pendingTasks.value.clear()
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

    // Append history immediately
    history.value.unshift({
      round: currentScene.value.round,
      narrative: `[你的選擇] ${optionId} (${attitudeSelections.map(x => `${x.dimension}:${x.level}`).join(', ') || '默認態度'})`,
      timestamp: new Date().toISOString(),
      choice_made: optionId,
    })

    // Custom offline simulation bypass
    if (characterId.value.startsWith('custom_char_')) {
      setTimeout(() => {
        simulateOfflineTurn(optionId, attitudeSelections)
      }, 1500)
      return
    }

    setTimeout(() => {
      if (pendingTasks.value.size > 0) {
        pendingTasks.value.clear()
      }
    }, 30000)

    wsService.send({
      type: 'action_submit',
      round: currentScene.value.round,
      character_id: characterId.value,
      choice: {
        option_id: optionId,
        attitude_selections: attitudeSelections,
      },
    })
  }

  function simulateOfflineTurn(
    optionId: string,
    attitudeSelections: Array<{ dimension: string; level: string }>
  ) {
    if (!characterState.value || !currentScene.value || !characterId.value) return

    // Bumps round
    clientRound.value += 1
    const nextRound = clientRound.value

    // Randomize state adjustments based on choices
    const state = { ...characterState.value }
    const staminaLevels = ['fresh', 'slight_breath', 'muscle_ache', 'exhausted', 'collapse']
    const healthLevels = ['healthy', 'wounded', 'severely_wounded', 'dying', 'dead']
    const moraleLevels = ['elated', 'calm', 'neutral', 'anxious', 'despair']

    // Update physical and mental state slightly
    let staminaIdx = staminaLevels.indexOf(state.physical.stamina_level)
    let healthIdx = healthLevels.indexOf(state.physical.health_status)
    let moraleIdx = moraleLevels.indexOf(state.mental.morale_level)

    // Modify indices randomly
    if (Math.random() > 0.6) {
      staminaIdx = Math.min(staminaLevels.length - 1, staminaIdx + 1)
    }
    if (Math.random() > 0.8) {
      healthIdx = Math.min(healthLevels.length - 1, healthIdx + 1)
    }
    if (Math.random() > 0.7) {
      moraleIdx = Math.min(moraleLevels.length - 1, moraleIdx + 1)
    }

    state.physical.stamina_level = staminaLevels[staminaIdx]
    state.physical.health_status = healthLevels[healthIdx]
    state.mental.morale_level = moraleLevels[moraleIdx]

    // Randomly loot a new item
    if (Math.random() > 0.5) {
      const newItemId = RANDOM_LOOT[Math.floor(Math.random() * RANDOM_LOOT.length)]
      const existing = state.inventory.items.find(x => x.item_id === newItemId)
      if (existing) {
        existing.quantity += 1
      } else {
        state.inventory.items.push({ item_id: newItemId, quantity: 1 })
      }
      history.value.unshift({
        round: nextRound,
        narrative: `⚡ [獲得物品] 你在探索過程中，意外尋獲了 ${newItemId}。`,
        timestamp: new Date().toISOString()
      })
    }

    // Set next scene from offline preset library
    const preset = OFFLINE_SCENES[Math.floor(Math.random() * OFFLINE_SCENES.length)]
    const nextScene: SceneOutput = {
      round: nextRound,
      character_id: characterId.value,
      narrative: preset.narrative,
      state_changes: {
        stamina_level: state.physical.stamina_level,
        health_status: state.physical.health_status,
        morale_level: state.mental.morale_level
      },
      choices: preset.choices,
      minor_event: Math.random() > 0.7 ? '周圍傳來狼嚎，氣溫急速下降。' : undefined
    }

    // Update stores
    characterState.value = state
    currentScene.value = nextScene

    // Persist to LocalStorage
    localStorage.setItem(`openclaw_char_${characterId.value}`, JSON.stringify(state))
    localStorage.setItem(`openclaw_scene_${characterId.value}`, JSON.stringify(nextScene))

    // Clear loading
    pendingTasks.value.clear()
    console.log(`[Simulator] Turn completed. Round ${nextRound} generated.`)
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
