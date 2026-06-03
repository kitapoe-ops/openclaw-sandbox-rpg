<script setup lang="ts">
defineProps<{
  state: any
}>()
</script>

<template>
  <div class="character-status" v-if="state">
    <h3>角色狀態</h3>

    <div class="status-section">
      <h4>身體</h4>
      <div class="status-row">
        <span class="label">體力：</span>
        <span class="value">{{ state.physical?.stamina_level }}</span>
      </div>
      <div class="status-row">
        <span class="label">健康：</span>
        <span class="value">{{ state.physical?.health_status }}</span>
      </div>
      <div v-if="state.physical?.active_effects?.length" class="effects">
        <span class="effect-tag" v-for="effect in state.physical.active_effects" :key="effect">
          {{ effect }}
        </span>
      </div>
    </div>

    <div class="status-section">
      <h4>心智</h4>
      <div class="status-row">
        <span class="label">情緒：</span>
        <span class="value">{{ state.mental?.morale_level }}</span>
      </div>
      <div class="status-row">
        <span class="label">警覺：</span>
        <span class="value">{{ state.mental?.alertness_level }}</span>
      </div>
    </div>

    <div v-if="state.attitude" class="status-section">
      <h4>當前態度</h4>
      <div v-for="(level, dim) in state.attitude" :key="dim" class="status-row">
        <span class="label">{{ dim }}：</span>
        <span class="value">{{ level }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.character-status {
  background: rgba(255, 255, 255, 0.05);
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
}

h3 {
  color: var(--color-accent);
  margin-bottom: 1rem;
}

h4 {
  font-size: 0.9rem;
  margin: 1rem 0 0.5rem;
  opacity: 0.7;
}

.status-row {
  display: flex;
  justify-content: space-between;
  padding: 0.4rem 0;
  font-size: 0.95rem;
}

.label {
  opacity: 0.7;
}

.value {
  color: var(--color-accent);
  font-weight: 500;
}

.effects {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.effect-tag {
  padding: 0.3rem 0.7rem;
  background: rgba(255, 100, 100, 0.2);
  border: 1px solid rgba(255, 100, 100, 0.4);
  border-radius: 12px;
  font-size: 0.8rem;
}
</style>
