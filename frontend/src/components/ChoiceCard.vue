<script setup lang="ts">
import { ref, computed } from 'vue'

interface Choice {
  id: string
  vignette: string
  intent_category: string
  lore_source: string
  direction_hint: string
  attitude_options: Array<{
    dimension: string
    level: string
    effect?: string
  }>
}

const props = defineProps<{
  choice: Choice
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'select', payload: { optionId: string; attitudeSelections: any[] }): void
}>()

const selectedAttitudes = ref<Record<string, string>>({})
const isExpanded = ref(false)

// Phase L2-I: the choice UI no longer leaks meta tags to the player.
// `intent_category`, `lore_source`, `direction_hint` are still in
// the data model (LLM uses them server-side) but are not rendered.
// The `attitude_options` are also hidden by default — most players
// will just pick a vignette. Power users can expand for fine-tuning.

function selectAttitude(dimension: string, level: string) {
  if (props.disabled) return
  if (selectedAttitudes.value[dimension] === level) {
    const { [dimension]: _, ...rest } = selectedAttitudes.value
    selectedAttitudes.value = rest
  } else {
    if (Object.keys(selectedAttitudes.value).length >= 2 && !(dimension in selectedAttitudes.value)) {
      return // Max 2 attitudes
    }
    selectedAttitudes.value = { ...selectedAttitudes.value, [dimension]: level }
  }
}

function quickPick() {
  if (props.disabled) return
  // No attitude selections — submit with empty array
  emit('select', { optionId: props.choice.id, attitudeSelections: [] })
}

function confirmChoice() {
  if (props.disabled) return
  if (Object.keys(selectedAttitudes.value).length === 0) return
  const attitudeSelections = Object.entries(selectedAttitudes.value).map(
    ([dimension, level]) => ({ dimension, level })
  )
  emit('select', { optionId: props.choice.id, attitudeSelections })
  selectedAttitudes.value = {}
}
</script>

<template>
  <div class="choice-card" :class="{ disabled }">
    <!-- Main vignette (the ONLY thing the player sees by default) -->
    <p class="vignette">{{ choice.vignette }}</p>

    <!-- Quick-pick: just click the card to choose this option immediately -->
    <button
      class="pick-btn"
      :disabled="disabled"
      @click="quickPick"
    >
      揀呢個
    </button>

    <!-- Optional: expand for attitude fine-tuning. Power users only. -->
    <details class="attitude-section" @toggle="isExpanded = ($event.target as HTMLDetailsElement).open">
      <summary>微調態度（可選）</summary>
      <div v-if="isExpanded" class="attitude-options">
        <div class="attitude-chips">
          <div
            v-for="att in choice.attitude_options"
            :key="att.dimension + att.level"
            class="attitude-chip"
            :class="{
              active: selectedAttitudes[att.dimension] === att.level,
            }"
            @click.stop="selectAttitude(att.dimension, att.level)"
          >
            <span class="att-dim">{{ att.dimension }}:</span>
            <span class="att-level">{{ att.level }}</span>
            <span v-if="att.effect" class="att-effect">— {{ att.effect }}</span>
          </div>
        </div>
        <button
          v-if="Object.keys(selectedAttitudes).length > 0"
          @click="confirmChoice"
          class="confirm-btn"
          :disabled="disabled"
        >
          確認（已選 {{ Object.keys(selectedAttitudes).length }} 個態度）
        </button>
      </div>
    </details>
  </div>
</template>

<style scoped>
.choice-card {
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  padding: 1rem;
  position: relative;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  min-height: 140px;
}

.choice-card:hover:not(.disabled) {
  border-color: var(--color-accent);
  background: rgba(0, 0, 0, 0.4);
}

.choice-card.disabled {
  opacity: 0.5;
}

.vignette {
  font-size: 0.95rem;
  line-height: 1.5;
  color: var(--color-text);
  flex: 1;
  margin: 0;
}

.pick-btn {
  width: 100%;
  padding: 0.6rem;
  background: transparent;
  color: var(--color-accent);
  border: 1px solid var(--color-accent);
  border-radius: 4px;
  font-size: 0.9rem;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.15s;
}

.pick-btn:hover:not(:disabled) {
  background: var(--color-accent);
  color: white;
}

.pick-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.attitude-section {
  border-top: 1px solid var(--color-border);
  padding-top: 0.5rem;
  margin-top: 0.25rem;
}

.attitude-section summary {
  cursor: pointer;
  font-size: 0.75rem;
  color: var(--color-text-muted);
  user-select: none;
  list-style: none;
  padding: 0.3rem 0;
  opacity: 0.6;
}

.attitude-section summary::before {
  content: '▸ ';
  display: inline-block;
  transition: transform 0.2s;
}

.attitude-section[open] summary::before {
  content: '▾ ';
}

.attitude-section summary::-webkit-details-marker {
  display: none;
}

.attitude-chips {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0.5rem 0;
}

.attitude-chip {
  padding: 0.3rem 0.5rem;
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.75rem;
  transition: all 0.15s;
  display: flex;
  gap: 0.3rem;
  flex-wrap: wrap;
}

.attitude-chip:hover:not(.disabled) {
  border-color: var(--color-accent);
}

.attitude-chip.active {
  background: var(--color-accent);
  color: white;
  border-color: var(--color-accent);
}

.att-dim {
  font-weight: 500;
  opacity: 0.8;
}

.att-level {
  font-weight: 500;
}

.att-effect {
  opacity: 0.7;
  font-style: italic;
}

.confirm-btn {
  width: 100%;
  padding: 0.5rem;
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 0.85rem;
  cursor: pointer;
  font-weight: 500;
}

.confirm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
