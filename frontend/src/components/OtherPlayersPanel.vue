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
  return [...props.actions].sort((a, b) => {
    const ta = new Date(a.timestamp).getTime()
    const tb = new Date(b.timestamp).getTime()
    return tb - ta
  })
})

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleTimeString('zh-HK', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="other-players-panel">
    <h4 class="panel-title">👥 其他玩家動態</h4>
    <p v-if="sorted.length === 0" class="empty-hint">
      （暫無其他玩家在凡達林冒險）
    </p>
    <div v-else class="action-list-wrapper">
      <ul class="action-list">
        <li v-for="a in sorted" :key="a.id" class="action-item" :class="{ 'state-changed': a.world_state_change }">
          <div class="action-head">
            <span class="actor-name">⚔️ {{ a.actor_name }}</span>
            <span class="action-time">{{ formatTime(a.timestamp) }}</span>
          </div>
          <p class="choice-text">{{ a.choice_text }}</p>
          <div v-if="a.world_event" class="world-event-tag">
            <span class="event-icon">⚡</span>
            <span class="event-desc">{{ a.world_event }}</span>
          </div>
          <div v-if="a.world_state_change" class="world-state-tag">
            <span class="state-icon">🌍</span>
            <span class="state-desc">引發世界線因果轉移</span>
          </div>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.other-players-panel {
  background: var(--color-glass-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-m);
  padding: 1rem;
  max-height: 280px;
  display: flex;
  flex-direction: column;
}

.panel-title {
  font-size: 0.85rem;
  margin: 0 0 0.6rem 0;
  color: var(--color-accent);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 0.4rem;
}

.empty-hint {
  font-size: 0.8rem;
  color: var(--color-text-muted);
  opacity: 0.65;
  margin: 1rem 0;
  text-align: center;
  font-style: italic;
}

.action-list-wrapper {
  overflow-y: auto;
  flex-grow: 1;
}

.action-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.action-item {
  background: rgba(0, 0, 0, 0.3);
  border-left: 3px solid var(--color-accent);
  padding: 0.5rem 0.75rem;
  border-radius: 0 var(--border-radius-s) var(--border-radius-s) 0;
  transition: var(--transition-smooth);
}

.action-item.state-changed {
  border-left-color: var(--color-warning);
  background: rgba(241, 196, 15, 0.04);
}

.action-head {
  display: flex;
  justify-content: space-between;
  font-size: 0.72rem;
  margin-bottom: 0.2rem;
}

.actor-name {
  font-weight: 600;
  color: var(--color-accent);
}

.action-time {
  opacity: 0.5;
  font-family: monospace;
}

.choice-text {
  font-size: 0.8rem;
  margin: 0;
  line-height: 1.5;
  color: var(--color-text);
  text-align: justify;
}

.world-event-tag, .world-state-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.3rem;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.7rem;
}

.world-event-tag {
  background: rgba(212, 175, 55, 0.12);
  border: 1px solid rgba(212, 175, 55, 0.25);
  color: var(--color-accent);
}

.world-state-tag {
  background: rgba(241, 196, 15, 0.12);
  border: 1px solid rgba(241, 196, 15, 0.25);
  color: var(--color-warning);
}

.event-icon, .state-icon {
  font-size: 0.75rem;
}

.event-desc, .state-desc {
  font-style: italic;
}
</style>
