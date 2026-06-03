<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useGameStore } from '@/stores/gameStore'
import { gameApi } from '@/services/api'
import ScenePanel from '@/components/ScenePanel.vue'
import ChoicePanel from '@/components/ChoicePanel.vue'
import CharacterStatus from '@/components/CharacterStatus.vue'
import Inventory from '@/components/Inventory.vue'
import Equipment from '@/components/Equipment.vue'
import CountdownTimer from '@/components/CountdownTimer.vue'
import HistoryLog from '@/components/HistoryLog.vue'

const route = useRoute()
const gameStore = useGameStore()
const characterId = route.params.characterId as string

onMounted(async () => {
  // 1. 載入角色狀態 (REST)
  try {
    const state = await gameApi.getCharacter(characterId)
    gameStore.setCharacterState(state)
  } catch (e) {
    console.error('Failed to load character state:', e)
  }

  // 2. 載入當前場景 (REST)
  try {
    const scene = await gameApi.getCurrentScene(characterId)
    gameStore.setCurrentScene(scene)
  } catch (e) {
    console.error('Failed to load current scene:', e)
  }

  // 3. 連接 WebSocket (即時更新)
  await gameStore.initialize(characterId)
})

onUnmounted(() => {
  gameStore.cleanup()
})

function handleChoice(payload: { optionId: string; attitudeSelections: any[] }) {
  gameStore.submitChoice(payload.optionId, payload.attitudeSelections)
}
</script>

<template>
  <div class="game-view">
    <div class="left-panel">
      <ScenePanel :scene="gameStore.currentScene" />
      <ChoicePanel
        v-if="gameStore.currentScene?.choices"
        :choices="gameStore.currentScene.choices"
        @select="handleChoice"
      />
    </div>

    <div class="right-panel">
      <div class="connection-status" :class="{ connected: gameStore.isConnected }">
        {{ gameStore.isConnected ? '🟢 已連接' : '🔴 斷線' }}
      </div>

      <CharacterStatus
        v-if="gameStore.characterState"
        :state="gameStore.characterState"
      />

      <CountdownTimer :remaining-seconds="gameStore.remainingSeconds" />

      <Equipment
        v-if="gameStore.characterState?.inventory.equipment"
        :equipment="gameStore.characterState.inventory.equipment"
      />

      <Inventory
        v-if="gameStore.characterState?.inventory.items"
        :items="gameStore.characterState.inventory.items"
      />

      <HistoryLog :history="gameStore.history" />
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

.connection-status {
  padding: 0.5rem 1rem;
  background: rgba(255, 100, 100, 0.2);
  border: 1px solid rgba(255, 100, 100, 0.4);
  border-radius: 4px;
  text-align: center;
  font-size: 0.85rem;
}

.connection-status.connected {
  background: rgba(100, 255, 100, 0.2);
  border-color: rgba(100, 255, 100, 0.4);
}

@media (max-width: 1024px) {
  .game-view {
    grid-template-columns: 1fr;
  }
}
</style>
