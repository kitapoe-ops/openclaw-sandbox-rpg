<script setup lang="ts">
defineProps<{
  history: any[]
}>()
</script>

<template>
  <div class="history-log" v-if="history">
    <h3>歷史日誌</h3>
    <div v-if="history.length === 0" class="empty">未有記錄</div>
    <div v-else class="entries">
      <div v-for="(entry, idx) in history" :key="idx" class="entry">
        <div class="round">第 {{ entry.round }} 輪</div>
        <div class="narrative">{{ entry.narrative?.substring(0, 100) }}...</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.history-log {
  background: rgba(255, 255, 255, 0.05);
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  max-height: 400px;
  overflow-y: auto;
}

h3 {
  color: var(--color-accent);
  margin-bottom: 1rem;
}

.empty {
  text-align: center;
  opacity: 0.5;
  padding: 1rem 0;
}

.entries {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.entry {
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  font-size: 0.85rem;
}

.round {
  color: var(--color-accent);
  font-weight: 500;
  margin-bottom: 0.3rem;
}

.narrative {
  opacity: 0.8;
  line-height: 1.5;
}
</style>
