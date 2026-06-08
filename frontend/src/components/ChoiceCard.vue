<script setup lang="ts">
import { ref } from 'vue'

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

function selectAttitude(dimension: string, level: string) {
  if (props.disabled) return
  if (selectedAttitudes.value[dimension] === level) {
    const { [dimension]: _, ...rest } = selectedAttitudes.value
    selectedAttitudes.value = rest
  } else {
    if (Object.keys(selectedAttitudes.value).length >= 2 && !(dimension in selectedAttitudes.value)) {
      return
    }
    selectedAttitudes.value = { ...selectedAttitudes.value, [dimension]: level }
  }
}

function quickPick() {
  if (props.disabled) return
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

function formatDimension(dim: string): string {
  const mapping: Record<string, string> = {
    caution: '謹慎度',
    empathy: '同理心',
    honor: '榮譽感',
    curiosity: '好奇心',
    violence: '暴力傾向'
  }
  return mapping[dim] || dim
}

function formatLevel(level: string): string {
  const mapping: Record<string, string> = {
    reckless: '魯莽', bold: '大膽', careful: '小心', timid: '膽怯',
    ruthless: '冷酷', pragmatic: '實用', compassionate: '同理', selfless: '無私',
    deceitful: '欺瞞', flexible: '靈活', honest: '誠實', righteous: '正直',
    indifferent: '冷漠', practical: '務實', curious: '好奇', obsessed: '狂熱',
    pacifist: '和平', defensive: '防衛', balanced: '平衡', aggressive: '侵略'
  }
  return mapping[level] || level
}
</script>

<template>
  <div class="choice-card" :class="{ disabled }">
    <div class="card-header">
      <span class="category-tag" :class="choice.intent_category">
        {{ choice.intent_category?.toUpperCase() }}
      </span>
      <span class="direction-hint" v-if="choice.direction_hint">
        {{ choice.direction_hint }}
      </span>
    </div>

    <!-- Main vignette -->
    <p class="vignette">{{ choice.vignette }}</p>

    <!-- Quick-pick button -->
    <button
      class="pick-btn"
      :disabled="disabled"
      @click="quickPick"
    >
      <span class="shine"></span>
      選 擇 此 途
    </button>

    <!-- Attitude accordion -->
    <details class="attitude-section" @toggle="isExpanded = ($event.target as HTMLDetailsElement).open">
      <summary class="attitude-summary">
        <span class="summary-arrow">✦</span>
        微調態度 (選填，最多2個)
      </summary>
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
            <span class="att-dim">{{ formatDimension(att.dimension) }}</span>
            <span class="att-divider">·</span>
            <span class="att-level">{{ formatLevel(att.level) }}</span>
            <span v-if="att.effect" class="att-effect">({{ att.effect }})</span>
          </div>
        </div>
        <button
          v-if="Object.keys(selectedAttitudes).length > 0"
          @click="confirmChoice"
          class="confirm-btn"
          :disabled="disabled"
        >
          確認態度（已選 {{ Object.keys(selectedAttitudes).length }} 個）
        </button>
      </div>
    </details>
  </div>
</template>

<style scoped>
.choice-card {
  background: rgba(18, 13, 36, 0.45);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-m);
  padding: 1.2rem;
  transition: var(--transition-smooth);
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
  min-height: 180px;
  box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
}

.choice-card:hover:not(.disabled) {
  border-color: rgba(212, 175, 55, 0.45);
  background: rgba(26, 20, 48, 0.65);
  transform: translateY(-3px);
  box-shadow: var(--shadow-glow);
}

.choice-card.disabled {
  opacity: 0.4;
  pointer-events: none;
}

.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 0.75rem;
}

.category-tag {
  font-size: 0.65rem;
  font-weight: 700;
  padding: 0.15rem 0.45rem;
  border-radius: 4px;
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
  letter-spacing: 0.05em;
}

.category-tag.action { background: rgba(231, 76, 60, 0.25); color: #e74c3c; border: 1px solid rgba(231, 76, 60, 0.3); }
.category-tag.talk { background: rgba(52, 152, 219, 0.25); color: #3498db; border: 1px solid rgba(52, 152, 219, 0.3); }
.category-tag.explore { background: rgba(46, 204, 113, 0.25); color: #2ecc71; border: 1px solid rgba(46, 204, 113, 0.3); }
.category-tag.creative { background: rgba(155, 89, 182, 0.25); color: #9b59b6; border: 1px solid rgba(155, 89, 182, 0.3); }

.direction-hint {
  color: var(--color-text-muted);
  font-style: italic;
  font-weight: 500;
}

.vignette {
  font-size: 0.92rem;
  line-height: 1.6;
  color: var(--color-text);
  opacity: 0.9;
  flex: 1;
  margin: 0;
}

/* Premium Choice Button */
.pick-btn {
  position: relative;
  width: 100%;
  padding: 0.65rem;
  background: transparent;
  color: var(--color-accent);
  border: 1px solid var(--color-accent);
  border-radius: var(--border-radius-s);
  font-size: 0.88rem;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition-smooth);
  overflow: hidden;
  letter-spacing: 0.05em;
}

.pick-btn:hover:not(:disabled) {
  background: var(--color-accent);
  color: #07050d;
  box-shadow: 0 4px 10px rgba(212, 175, 55, 0.3);
}

.attitude-section {
  border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 0.6rem;
  margin-top: 0.2rem;
}

.attitude-summary {
  cursor: pointer;
  font-size: 0.78rem;
  color: var(--color-text-muted);
  user-select: none;
  list-style: none;
  padding: 0.2rem 0;
  display: flex;
  align-items: center;
  gap: 0.4rem;
  transition: var(--transition-smooth);
}

.attitude-summary:hover {
  color: var(--color-accent);
}

.summary-arrow {
  font-size: 0.6rem;
  transition: transform 0.2s;
  color: var(--color-accent);
}

.attitude-section[open] .summary-arrow {
  transform: rotate(45deg);
}

.attitude-summary::-webkit-details-marker {
  display: none;
}

.attitude-options {
  animation: slide-down 0.25s ease-out;
}

@keyframes slide-down {
  from { opacity: 0; transform: translateY(-5px); }
  to { opacity: 1; transform: translateY(0); }
}

.attitude-chips {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0.6rem 0;
}

.attitude-chip {
  padding: 0.4rem 0.6rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-s);
  cursor: pointer;
  font-size: 0.78rem;
  transition: var(--transition-smooth);
  display: flex;
  align-items: center;
  gap: 0.4rem;
  flex-wrap: wrap;
}

.attitude-chip:hover {
  border-color: rgba(212, 175, 55, 0.4);
  background: rgba(212, 175, 55, 0.03);
}

.attitude-chip.active {
  background: linear-gradient(135deg, var(--color-accent) 0%, #a38120 100%);
  color: #07050d;
  border-color: var(--color-accent);
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(212, 175, 55, 0.25);
}

.att-dim {
  opacity: 0.85;
}

.attitude-chip.active .att-dim {
  opacity: 1;
}

.att-divider {
  opacity: 0.4;
}

.att-level {
  font-weight: 600;
}

.att-effect {
  opacity: 0.7;
  font-size: 0.72rem;
  font-style: italic;
}

.confirm-btn {
  width: 100%;
  padding: 0.5rem;
  background: var(--color-accent);
  color: #07050d;
  border: none;
  border-radius: var(--border-radius-s);
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(212, 175, 55, 0.2);
  transition: var(--transition-smooth);
}

.confirm-btn:hover:not(:disabled) {
  background: var(--color-accent-hover);
  box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4);
}
</style>
