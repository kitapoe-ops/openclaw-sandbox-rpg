<script setup lang="ts">
defineProps<{
  equipment: Record<string, string | undefined>
}>()

const slots = [
  { key: 'weapon', label: '武器' },
  { key: 'armor', label: '防具' },
  { key: 'accessory_1', label: '飾品 1' },
  { key: 'accessory_2', label: '飾品 2' },
]
</script>

<template>
  <div class="equipment">
    <h3>裝備</h3>
    <div class="slots">
      <div v-for="slot in slots" :key="slot.key" class="slot">
        <span class="slot-label">{{ slot.label }}</span>
        <span class="slot-value">{{ equipment?.[slot.key] || '空' }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.equipment {
  background: rgba(255, 255, 255, 0.05);
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

h3 {
  color: var(--color-accent);
  margin-bottom: 1rem;
}

.slots {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.slot {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  font-size: 0.9rem;
}

.slot-label {
  opacity: 0.7;
}

.slot-value {
  color: var(--color-accent);
  font-size: 0.85rem;
}
</style>
