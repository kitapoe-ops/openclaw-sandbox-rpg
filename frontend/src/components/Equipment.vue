<script setup lang="ts">
defineProps<{
  equipment: Record<string, string | undefined>
}>()

const slots = [
  { key: 'weapon', label: '武器槽', icon: '⚔️' },
  { key: 'armor', label: '防具槽', icon: '🛡️' },
  { key: 'accessory_1', label: '飾品一', icon: '💍' },
  { key: 'accessory_2', label: '飾品二', icon: '🔮' },
]
</script>

<template>
  <div class="equipment-panel">
    <h3>配備裝備</h3>
    <div class="equipment-grid">
      <div v-for="slot in slots" :key="slot.key" class="equipment-slot-card">
        <div class="slot-icon-container">
          <span class="slot-default-icon" v-if="!equipment?.[slot.key]">{{ slot.icon }}</span>
          <span class="slot-equipped-icon" v-else>✨</span>
        </div>
        <div class="slot-info">
          <span class="slot-label">{{ slot.label }}</span>
          <span class="slot-value" :class="{ equipped: equipment?.[slot.key] }">
            {{ equipment?.[slot.key] || '無裝備' }}
          </span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.equipment-panel {
  background: var(--color-glass-bg);
  padding: 1.5rem;
  border-radius: var(--border-radius-m);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(12px);
}

h3 {
  color: var(--color-accent);
  margin-bottom: 1rem;
  font-size: 1.15rem;
}

.equipment-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.8rem;
}

.equipment-slot-card {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.8rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-m);
  transition: var(--transition-smooth);
}

.equipment-slot-card:hover {
  border-color: rgba(212, 175, 55, 0.35);
  background: rgba(26, 20, 48, 0.45);
}

.slot-icon-container {
  width: 38px;
  height: 38px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: var(--border-radius-s);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
  box-shadow: inset 0 0 5px rgba(0, 0, 0, 0.5);
}

.equipment-slot-card:has(.equipped) .slot-icon-container {
  border-color: var(--color-accent);
  background: rgba(212, 175, 55, 0.08);
  box-shadow: 0 0 8px rgba(212, 175, 55, 0.15);
}

.slot-default-icon {
  opacity: 0.35;
}

.slot-equipped-icon {
  filter: drop-shadow(0 0 3px var(--color-accent));
}

.slot-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.slot-label {
  font-size: 0.72rem;
  opacity: 0.45;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.slot-value {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--color-text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.slot-value.equipped {
  color: var(--color-accent);
  font-weight: 600;
  text-shadow: 0 0 5px rgba(212, 175, 55, 0.1);
}
</style>
