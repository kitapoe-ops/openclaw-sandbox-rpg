<script setup lang="ts">
defineProps<{
  history: any[]
}>()

function cleanNarrative(text: string): string {
  if (!text) return ''
  // Strip starting bracket tags like [你的選擇] or [世界事件] for cleaner presentation
  return text.replace(/^\[.*?\]\s*/, '')
}

function getPrefix(text: string): string {
  if (!text) return '✦'
  if (text.startsWith('[你的選擇]')) return '🧭'
  if (text.startsWith('[世界事件]')) return '⚡'
  return '✦'
}
</script>

<template>
  <div class="history-log-panel" v-if="history">
    <h3>冒險編年史</h3>
    <div v-if="history.length === 0" class="empty-state">
      <span class="empty-icon">📜</span>
      <p>未有編年史記載。</p>
    </div>
    <div v-else class="timeline-container">
      <div v-for="(entry, idx) in history" :key="idx" class="timeline-item">
        <div class="timeline-node">
          <span class="node-icon">{{ getPrefix(entry.narrative) }}</span>
        </div>
        <div class="timeline-content">
          <div class="timeline-header">
            <span class="timeline-round">第 {{ entry.round }} 輪</span>
          </div>
          <p class="timeline-desc" :title="entry.narrative">
            {{ cleanNarrative(entry.narrative) }}
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-log-panel {
  background: var(--color-glass-bg);
  padding: 1.5rem;
  border-radius: var(--border-radius-m);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(12px);
  max-height: 380px;
  display: flex;
  flex-direction: column;
}

h3 {
  color: var(--color-accent);
  margin-bottom: 1.2rem;
  font-size: 1.15rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem 0;
  opacity: 0.5;
  text-align: center;
}

.empty-icon {
  font-size: 1.8rem;
}

.empty-state p {
  font-size: 0.82rem;
  font-style: italic;
}

.timeline-container {
  display: flex;
  flex-direction: column;
  position: relative;
  padding-left: 1.2rem;
  border-left: 1px dashed rgba(212, 175, 55, 0.25);
  gap: 1.2rem;
  overflow-y: auto;
  flex-grow: 1;
}

.timeline-item {
  position: relative;
  display: flex;
  flex-direction: column;
  animation: slide-in 0.3s ease-out;
}

@keyframes slide-in {
  from { opacity: 0; transform: translateX(-10px); }
  to { opacity: 1; transform: translateX(0); }
}

.timeline-node {
  position: absolute;
  left: -1.7rem;
  top: 0.1rem;
  width: 16px;
  height: 16px;
  background: var(--color-bg);
  border: 1px solid var(--color-accent);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2;
  box-shadow: 0 0 5px rgba(212, 175, 55, 0.4);
}

.node-icon {
  font-size: 0.65rem;
}

.timeline-content {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-m);
  padding: 0.6rem 0.8rem;
}

.timeline-header {
  display: flex;
  align-items: center;
  margin-bottom: 0.2rem;
}

.timeline-round {
  font-size: 0.72rem;
  font-weight: 700;
  color: var(--color-accent);
}

.timeline-desc {
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--color-text);
  opacity: 0.85;
  margin: 0;
  text-align: justify;
}
</style>
