<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  choices: any[]
}>()

const emit = defineEmits<{
  (e: 'select', payload: { optionId: string; attitudeSelections: any[] }): void
}>()

const selectedOption = ref<string | null>(null)
const selectedAttitudes = ref<Record<string, string>>({})

function selectOption(optionId: string) {
  selectedOption.value = optionId
  selectedAttitudes.value = {}
}

function selectAttitude(dimension: string, level: string) {
  if (selectedAttitudes.value[dimension]) {
    const { [dimension]: _, ...rest } = selectedAttitudes.value
    selectedAttitudes.value = rest
  } else {
    if (Object.keys(selectedAttitudes.value).length >= 2) {
      // Max 2 attitudes
      return
    }
    selectedAttitudes.value = { ...selectedAttitudes.value, [dimension]: level }
  }
}

function confirmChoice() {
  if (!selectedOption.value) return
  const attitudeSelections = Object.entries(selectedAttitudes.value).map(
    ([dimension, level]) => ({ dimension, level })
  )
  emit('select', { optionId: selectedOption.value, attitudeSelections })
}
</script>

<template>
  <div class="choice-panel" v-if="choices">
    <h3>你嘅選擇</h3>

    <div class="options">
      <div
        v-for="choice in choices"
        :key="choice.id"
        class="option"
        :class="{ selected: selectedOption === choice.id }"
        @click="selectOption(choice.id)"
      >
        {{ choice.text }}
      </div>
    </div>

    <div v-if="selectedOption" class="attitudes">
      <h4>選擇態度（1-2 個）</h4>
      <div
        v-for="choice in choices.filter(c => c.id === selectedOption)"
        :key="choice.id"
        class="attitude-options"
      >
        <div
          v-for="att in choice.attitude_options"
          :key="att.dimension + att.level"
          class="attitude-chip"
          :class="{ active: selectedAttitudes[att.dimension] === att.level }"
          @click="selectAttitude(att.dimension, att.level)"
        >
          {{ att.dimension }}: {{ att.level }}
        </div>
      </div>
    </div>

    <button
      v-if="selectedOption && Object.keys(selectedAttitudes).length > 0"
      @click="confirmChoice"
      class="confirm-btn"
    >
      確認
    </button>
  </div>
</template>

<style scoped>
.choice-panel {
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
  margin: 1.5rem 0 0.75rem;
  font-size: 0.95rem;
  opacity: 0.8;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.option {
  padding: 1rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.option:hover {
  border-color: var(--color-accent);
}

.option.selected {
  border-color: var(--color-accent);
  background: rgba(183, 141, 74, 0.15);
}

.attitude-options {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.attitude-chip {
  padding: 0.4rem 0.8rem;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid var(--color-border);
  border-radius: 20px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.2s;
}

.attitude-chip:hover {
  border-color: var(--color-accent);
}

.attitude-chip.active {
  background: var(--color-accent);
  color: white;
  border-color: var(--color-accent);
}

.confirm-btn {
  margin-top: 1.5rem;
  width: 100%;
  padding: 0.75rem;
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
}

.confirm-btn:hover {
  opacity: 0.9;
}
</style>
