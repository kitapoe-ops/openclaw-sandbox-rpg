<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useGameStore } from '@/stores/gameStore'
import { gameApi } from '@/services/api'
import ScenePanel from '@/components/ScenePanel.vue'
import ChoiceCard from '@/components/ChoiceCard.vue'
import CharacterStatus from '@/components/CharacterStatus.vue'
import Inventory from '@/components/Inventory.vue'
import Equipment from '@/components/Equipment.vue'
import HistoryLog from '@/components/HistoryLog.vue'

const route = useRoute()
const gameStore = useGameStore()
const characterId = route.params.characterId as string

onMounted(async () => {
  try {
    const state = await gameApi.getCharacter(characterId)
    gameStore.setCharacterState(state)
  } catch (e) {
    console.error('Failed to load character state:', e)
  }

  try {
    const scene = await gameApi.getCurrentScene(characterId)
    gameStore.setCurrentScene(scene)
  } catch (e) {
    console.error('Failed to load current scene:', e)
  }

  await gameStore.initialize(characterId)
})

onUnmounted(() => {
  gameStore.cleanup()
})

// Mobile detection for responsive layout
const isMobile = computed(() => {
  if (typeof window === 'undefined') return false
  return window.innerWidth < 768
})

async function handleChoice(payload: { optionId: string; attitudeSelections: any[] }) {
  // Phase L2-I: free-for-all. Each player submits at their own pace;
  // no waiting for other players. The round-system has been removed
  // from the backend; the next scene is generated for THIS character
  // immediately on submit.
  gameStore.submitChoice(payload.optionId, payload.attitudeSelections)
}
</script>

<template>
  <div class="game-view" :class="{ mobile: isMobile }">
    <div class="left-panel">
      <ScenePanel :scene="gameStore.currentScene" />

      <!-- 4 Choice Cards arranged in responsive grid -->
      <div class="choices-container">
        <h3 class="choices-title">你的選擇</h3>
        <p class="choices-hint">4 個故事方向，每個係一個獨立嘅故事起點。揀邊個，由你決定。</p>

        <div class="choices-grid">
          <ChoiceCard
            v-for="choice in gameStore.currentScene?.choices"
            :key="choice.id"
            :choice="choice"
            :disabled="gameStore.isProcessing"
            @select="(payload) => handleChoice(payload)"
          />
        </div>
      </div>
    </div>

    <div class="right-panel">
      <div class="connection-status" :class="{ connected: gameStore.isConnected }">
        {{ gameStore.isConnected ? '🟢 已連接' : '🔴 斷線' }}
        <span v-if="gameStore.isReclaiming" class="reclaim-tag">重新連線中...</span>
      </div>

      <CharacterStatus
        v-if="gameStore.characterState"
        :state="gameStore.characterState"
      />

      <!-- Phase L2-I: CountdownTimer removed. Free-for-all pace. -->

      <Equipment
        v-if="gameStore.characterState?.inventory.equipment"
        :equipment="gameStore.characterState.inventory.equipment"
      />

      <Inventory
        v-if="gameStore.characterState?.inventory.items"
        :items="gameStore.characterState.inventory.items"
      />

      <HistoryLog :history="gameStore.history" />

      <!-- State mismatch warning -->
      <div v-if="gameStore.stateMismatchWarning" class="state-mismatch-warning">
        ⚠️ 場景狀態已過期，已自動重新整理
        <button @click="gameStore.clearStateMismatch">知道了</button>
      </div>

      <!-- Interrupted action notice -->
      <div v-if="gameStore.lastActionInterrupted" class="interrupted-notice">
        ⚠️ 上一個行動因伺服器重啟而被中斷，請重新選擇
        <button @click="gameStore.lastActionInterrupted = false">知道了</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.game-view {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1.5rem;
  padding: 1.5rem;
  max-width: 1600px;
  margin: 0 auto;
  min-height: 100vh;
}

.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.choices-container {
  background: rgba(255, 255, 255, 0.05);
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

.choices-title {
  color: var(--color-accent);
  margin-bottom: 0.5rem;
  font-size: 1.1rem;
}

.choices-hint {
  font-size: 0.85rem;
  opacity: 0.6;
  margin-bottom: 1rem;
  font-style: italic;
}

.choices-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);  /* 2x2 grid on desktop */
  gap: 1rem;
}

.connection-status {
  padding: 0.5rem 1rem;
  background: rgba(255, 100, 100, 0.2);
  border: 1px solid rgba(255, 100, 100, 0.4);
  border-radius: 4px;
  text-align: center;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.connection-status.connected {
  background: rgba(100, 255, 100, 0.2);
  border-color: rgba(100, 255, 100, 0.4);
}

.reclaim-tag {
  font-size: 0.75rem;
  opacity: 0.7;
  font-style: italic;
}

.state-mismatch-warning,
.interrupted-notice {
  padding: 0.75rem;
  background: rgba(255, 200, 0, 0.15);
  border: 1px solid rgba(255, 200, 0, 0.4);
  border-radius: 4px;
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.state-mismatch-warning button,
.interrupted-notice button {
  padding: 0.3rem 0.6rem;
  background: transparent;
  border: 1px solid currentColor;
  color: inherit;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
}

/* Mobile: stack choices vertically, single column */
.game-view.mobile .choices-grid {
  grid-template-columns: 1fr;
}

@media (max-width: 1024px) {
  .game-view {
    grid-template-columns: 1fr;
  }
  .choices-grid {
    grid-template-columns: 1fr;  /* Mobile: 1 column */
  }
}
</style>
