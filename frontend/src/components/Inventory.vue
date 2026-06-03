<script setup lang="ts">
defineProps<{
  items: Array<{ item_id: string; quantity: number }>
}>()
</script>

<template>
  <div class="inventory" v-if="items">
    <h3>背包</h3>
    <div v-if="items.length === 0" class="empty">空</div>
    <div class="items">
      <div v-for="item in items" :key="item.item_id" class="item">
        <span class="item-name">{{ item.item_id }}</span>
        <span class="item-qty">×{{ item.quantity }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.inventory {
  background: rgba(255, 255, 255, 0.05);
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
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

.items {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.item {
  display: flex;
  justify-content: space-between;
  padding: 0.5rem 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  font-size: 0.9rem;
}

.item-qty {
  color: var(--color-accent);
  font-weight: 500;
}
</style>
