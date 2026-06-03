<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import ScenePanel from '@/components/ScenePanel.vue'
import ChoicePanel from '@/components/ChoicePanel.vue'
import CharacterStatus from '@/components/CharacterStatus.vue'
import Inventory from '@/components/Inventory.vue'
import Equipment from '@/components/Equipment.vue'
import CountdownTimer from '@/components/CountdownTimer.vue'
import HistoryLog from '@/components/HistoryLog.vue'

const route = useRoute()
const characterId = route.params.characterId as string

// TODO: Implement WebSocket connection + state management
const currentScene = ref<any>(null)
const characterState = ref<any>(null)
const history = ref<any[]>([])

onMounted(() => {
  // TODO: Connect to WebSocket
  // TODO: Load initial scene
  console.log(`Game started for character: ${characterId}`)
})

onUnmounted(() => {
  // TODO: Disconnect WebSocket
})
</script>

<template>
  <div class="game-view">
    <div class="left-panel">
      <ScenePanel :scene="currentScene" />
      <ChoicePanel :choices="currentScene?.choices" v-if="currentScene" />
    </div>

    <div class="right-panel">
      <CharacterStatus :state="characterState" v-if="characterState" />
      <CountdownTimer :round-duration="15" />
      <Equipment :equipment="characterState?.inventory?.equipment" v-if="characterState" />
      <Inventory :items="characterState?.inventory?.items" v-if="characterState" />
      <HistoryLog :history="history" />
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

@media (max-width: 1024px) {
  .game-view {
    grid-template-columns: 1fr;
  }
}
</style>
