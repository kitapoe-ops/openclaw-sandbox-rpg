<script setup lang="ts">
defineProps<{
  scene: any
}>()

function cleanLocationName(id: string): string {
  if (!id) return '未知領域'
  // Convert loc_phandalin_town to "Phandalin Town" or a human-friendly format
  return id
    .replace('loc_', '')
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}
</script>

<template>
  <div class="scene-panel">
    <div v-if="scene" class="scene-content">
      <div class="scene-header">
        <span class="round-counter">ROUND {{ scene.round }}</span>
        <h2 class="location-title">📍 {{ cleanLocationName(scene.scene_id) }}</h2>
      </div>
      <div class="narrative">
        <p v-for="(paragraph, idx) in scene.narrative?.split('\n').filter(Boolean)"
           :key="idx" class="narrative-p">
          {{ paragraph }}
        </p>
      </div>
      <div v-if="scene.minor_event" class="minor-event-alert animate-pulse">
        <span class="alert-icon">⚡</span>
        <span class="alert-text">{{ scene.minor_event }}</span>
      </div>
    </div>
    <div v-else class="loading-container">
      <div class="spinner"></div>
      <span class="loading-text">正在讀取費倫大陸的記憶...</span>
    </div>
  </div>
</template>

<style scoped>
.scene-panel {
  background: var(--color-glass-bg);
  padding: 2.2rem;
  border-radius: var(--border-radius-m);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(12px);
  min-height: 280px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.scene-content {
  animation: fade-in 0.6s ease-out;
}

@keyframes fade-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

.scene-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 0.8rem;
  margin-bottom: 1.5rem;
}

.round-counter {
  font-family: monospace;
  font-size: 0.8rem;
  font-weight: 700;
  color: #fff;
  background: var(--color-accent);
  color: #07050d;
  padding: 0.2rem 0.6rem;
  border-radius: 4px;
  letter-spacing: 0.1em;
}

.location-title {
  font-size: 1.15rem;
  color: var(--color-accent);
  margin: 0;
}

.narrative-p {
  margin-bottom: 1.2rem;
  line-height: 1.85;
  font-size: 1.05rem;
  text-align: justify;
  letter-spacing: 0.02em;
  opacity: 0.95;
}

.narrative-p:last-child {
  margin-bottom: 0;
}

.minor-event-alert {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-top: 1.5rem;
  padding: 0.75rem 1rem;
  background: rgba(212, 175, 55, 0.08);
  border: 1px solid rgba(212, 175, 55, 0.25);
  border-radius: var(--border-radius-s);
}

.alert-icon {
  font-size: 1rem;
  color: var(--color-accent);
}

.alert-text {
  font-size: 0.85rem;
  color: var(--color-accent);
  font-style: italic;
}

/* Premium Loading Spinner */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1.2rem;
  padding: 3rem 0;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(212, 175, 55, 0.1);
  border-top-color: var(--color-accent);
  border-radius: 50%;
  animation: spin 1s infinite linear;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.loading-text {
  font-size: 0.9rem;
  color: var(--color-text-muted);
  letter-spacing: 0.05em;
  font-style: italic;
}
</style>
