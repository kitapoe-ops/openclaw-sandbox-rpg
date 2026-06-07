<script setup lang="ts">
import { computed } from 'vue'

interface OtherAction {
  id: string
  actor_character_id: string
  actor_name: string
  choice_text: string
  world_event?: string
  world_state_change?: boolean
  timestamp: string
}

const props = defineProps<{
  actions: OtherAction[]
}>()

const sorted = computed(() => {
  // Most recent first
  return [...props.actions].sort((a, b) => {
    const ta = new Date(a.timestamp).getTime()
    const tb = new Date(b.timestamp).getTime()
    return tb - ta
  })
})

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-HK', { hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="other-players-panel">
    <h4 class="panel-title">其他玩家動態</h4>
    <p v-if="sorted.length === 0" class="empty-hint">
      （暫時冇其他玩家行動）
    </p>
    <ul v-else class="action-list">
      <li v-for="a in sorted" :key="a.id" class="action-item">
        <div class="action-head">
          <span class="actor-name">{{ a.actor_name }}</span>
          <span class="action-time">{{ formatTime(a.timestamp) }}</span>
        </div>
        <p class="choice-text">{{ a.choice_text }}</p>
        <p v-if="a.world_event" class="world-event">⚡ {{ a.world_event }}</p>
        <p v-if="a.world_state_change" class="world-state">🌍 場景狀態已改變</p>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.other-players-panel {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 0.75rem;
  max-height: 320px;
  overflow-y: auto;
}

.panel-title {
  font-size: 0.85rem;
  margin: 0 0 0.5rem 0;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.empty-hint {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  opacity: 0.6;
  margin: 0;
}

.action-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.action-item {
  background: rgba(0, 0, 0, 0.3);
  border-left: 2px solid var(--color-accent);
  padding: 0.4rem 0.6rem;
  border-radius: 0 4px 4px 0;
}

.action-head {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  margin-bottom: 0.2rem;
}

.actor-name {
  font-weight: 500;
  color: var(--color-accent);
}

.action-time {
  opacity: 0.6;
  font-family: monospace;
}

.choice-text {
  font-size: 0.85rem;
  margin: 0;
  line-height: 1.4;
}

.world-event {
  font-size: 0.75rem;
  margin: 0.2rem 0 0 0;
  color: var(--color-text-muted);
  font-style: italic;
}

.world-state {
  font-size: 0.7rem;
  margin: 0.2rem 0 0 0;
  opacity: 0.7;
}
</style>
