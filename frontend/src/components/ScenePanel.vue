<script setup lang="ts">
defineProps<{
  scene: any
}>()
</script>

<template>
  <div class="scene-panel">
    <div v-if="scene" class="narrative">
      <p v-for="(paragraph, idx) in scene.narrative?.split('\n').filter(Boolean)"
         :key="idx">
        {{ paragraph }}
      </p>
    </div>
    <div v-else class="loading">
      載入場景中...
    </div>
  </div>
</template>

<style scoped>
.scene-panel {
  background: rgba(255, 255, 255, 0.05);
  padding: 2rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  min-height: 300px;
}

.narrative p {
  margin-bottom: 1rem;
  line-height: 1.8;
  text-indent: 2em;
}

.loading {
  text-align: center;
  opacity: 0.5;
  padding: 3rem 0;
}
</style>
