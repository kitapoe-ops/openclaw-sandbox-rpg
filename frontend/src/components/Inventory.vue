<script setup lang="ts">
defineProps<{
  items: Array<{ item_id: string; quantity: number }>
}>()

function cleanItemName(id: string): string {
  if (!id) return ''
  // If id is item_rations_fine, clean it up or keep it if it has Chinese details
  return id
    .replace('item_', '')
    .replace(/_/g, ' ')
    .split(' ')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}
</script>

<template>
  <div class="inventory-panel" v-if="items">
    <h3>背包行囊</h3>
    <div v-if="items.length === 0" class="empty-state">
      <span class="empty-icon">🎒</span>
      <p>行囊空空如也，前路危機重重。</p>
    </div>
    <div v-else class="inventory-grid">
      <div v-for="item in items" :key="item.item_id" class="inventory-item-card">
        <div class="item-icon-box">🎒</div>
        <div class="item-details">
          <span class="item-name" :title="item.item_id">{{ item.item_id }}</span>
          <span class="item-qty-badge">×{{ item.quantity }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inventory-panel {
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

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1.5rem 0;
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

.inventory-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.8rem;
}

.inventory-item-card {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.6rem 0.8rem;
  background: rgba(0, 0, 0, 0.35);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-m);
  transition: var(--transition-smooth);
}

.inventory-item-card:hover {
  border-color: rgba(212, 175, 55, 0.3);
  background: rgba(26, 20, 48, 0.45);
}

.item-icon-box {
  width: 34px;
  height: 34px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--border-radius-s);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex-shrink: 0;
}

.item-details {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 0.4rem;
}

.item-name {
  font-size: 0.82rem;
  color: var(--color-text);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.item-qty-badge {
  font-size: 0.75rem;
  font-weight: 700;
  background: rgba(212, 175, 55, 0.15);
  border: 1px solid rgba(212, 175, 55, 0.3);
  color: var(--color-accent);
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  flex-shrink: 0;
}
</style>
