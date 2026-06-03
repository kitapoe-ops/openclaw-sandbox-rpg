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

// Dimension labels (Chinese)
const dimensionLabels: Record<string, string> = {
  character_growth: '角色成長',
  world_exploration: '世界探索',
  relationship: '關係建立',
  mystery_revelation: '謎團揭示',
}

const dimensionIcon = computed(() => {
  const icons: Record<string, string> = {
    character_growth: '👤',
    world_exploration: '🗺️',
    relationship: '🤝',
    mystery_revelation: '🔮',
  }
  return icons[props.choice.intent_category] || '📜'
})

const dimensionLabel = computed(() =>
  dimensionLabels[props.choice.intent_category] || props.choice.intent_category
)

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

function confirmChoice() {
  if (props.disabled) return
  if (Object.keys(selectedAttitudes.value).length === 0) return
  const attitudeSelections = Object.entries(selectedAttitudes.value).map(
    ([dimension, level]) => ({ dimension, level })
  )
  emit('select', { optionId: props.choice.id, attitudeSelections })
  selectedAttitudes.value = {}
}

const canConfirm = computed(() => Object.keys(selectedAttitudes.value).length > 0)
</script>

<template>
  <div class="choice-card" :class="{ disabled, selected: canConfirm }">
    <!-- Dimension badge (top corner) -->
    <div class="dimension-badge" :class="choice.intent_category">
      <span class="icon">{{ dimensionIcon }}</span>
      <span class="label">{{ dimensionLabel }}</span>
    </div>

    <!-- Main vignette (30-50 chars) -->
    <p class="vignette">{{ choice.vignette }}</p>

    <!-- Lore source (small, bottom corner) -->
    <div class="lore-source">
      <code>{{ choice.lore_source }}</code>
    </div>

    <!-- Expandable: direction hint + attitude options -->
    <details class="attitude-section" @toggle="isExpanded = $event.target.open">
      <summary>選擇態度 (1-2個)</summary>
      <div v-if="isExpanded" class="attitude-options">
        <p class="direction-hint">
          <em>💡 {{ choice.direction_hint }}</em>
        </p>
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
          v-if="canConfirm"
          @click="confirmChoice"
          class="confirm-btn"
          :disabled="disabled"
        >
          確認選擇
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
  min-height: 180px;
}

.choice-card:hover:not(.disabled) {
  border-color: var(--color-accent);
  background: rgba(0, 0, 0, 0.4);
}

.choice-card.selected:not(.disabled) {
  border-color: var(--color-accent);
  background: rgba(183, 141, 74, 0.1);
  box-shadow: 0 0 0 1px var(--color-accent);
}

.choice-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dimension-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.2rem 0.5rem;
  background: rgba(0, 0, 0, 0.5);
  border-radius: 4px;
  font-size: 0.7rem;
  align-self: flex-start;
  border: 1px solid currentColor;
}

.dimension-badge.character_growth {
  color: #d4a574;
}
.dimension-badge.world_exploration {
  color: #7ba3d4;
}
.dimension-badge.relationship {
  color: #c47bd4;
}
.dimension-badge.mystery_revelation {
  color: #d4c47b;
}

.dimension-badge .icon {
  font-size: 0.9rem;
}

.vignette {
  font-size: 0.95rem;
  line-height: 1.5;
  color: var(--color-text);
  flex: 1;
}

.lore-source {
  font-size: 0.7rem;
  opacity: 0.5;
}

.lore-source code {
  font-family: monospace;
  font-size: 0.7rem;
}

.attitude-section {
  border-top: 1px solid var(--color-border);
  padding-top: 0.5rem;
  margin-top: 0.25rem;
}

.attitude-section summary {
  cursor: pointer;
  font-size: 0.8rem;
  color: var(--color-accent);
  user-select: none;
  list-style: none;
  padding: 0.3rem 0;
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

.direction-hint {
  font-size: 0.8rem;
  opacity: 0.7;
  margin-bottom: 0.5rem;
  padding: 0.4rem 0.5rem;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  border-left: 2px solid var(--color-accent);
}

.attitude-chips {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin-bottom: 0.5rem;
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
  background: rgba(183, 141, 74, 0.1);
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

.confirm-btn:hover:not(:disabled) {
  opacity: 0.9;
}
</style>
