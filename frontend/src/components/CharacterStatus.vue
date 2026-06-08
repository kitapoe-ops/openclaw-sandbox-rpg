<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  state: any
}>()

// Stamina display map
const staminaInfo = computed(() => {
  const level = props.state?.physical?.stamina_level || 'fresh'
  const config: Record<string, { label: string; class: string; icon: string }> = {
    fresh: { label: '精神飽滿 (Fresh)', class: 'st-fresh', icon: '🟢' },
    slight_breath: { label: '輕微喘息 (Slight Breath)', class: 'st-breath', icon: '🔵' },
    muscle_ache: { label: '肌肉酸痛 (Muscle Ache)', class: 'st-ache', icon: '🟡' },
    exhausted: { label: '力竭 (Exhausted)', class: 'st-exhausted', icon: '🟠' },
    collapse: { label: '昏迷倒下 (Collapse)', class: 'st-collapse', icon: '🔴' }
  }
  return config[level] || { label: level, class: 'st-unknown', icon: '⚪' }
})

// Health display map
const healthInfo = computed(() => {
  const level = props.state?.physical?.health_status || 'healthy'
  const config: Record<string, { label: string; class: string; icon: string }> = {
    healthy: { label: '生龍活虎 (Healthy)', class: 'hl-healthy', icon: '🟢' },
    wounded: { label: '輕微受傷 (Wounded)', class: 'hl-wounded', icon: '🟡' },
    severely_wounded: { label: '身受重傷 (Severely Wounded)', class: 'hl-severe', icon: '🟠' },
    dying: { label: '命懸一線 (Dying)', class: 'hl-dying', icon: '🚨' },
    dead: { label: '魂歸天國 (Dead)', class: 'hl-dead', icon: '💀' }
  }
  return config[level] || { label: level, class: 'hl-unknown', icon: '⚪' }
})

// Morale display map
const moraleInfo = computed(() => {
  const level = props.state?.mental?.morale_level || 'calm'
  const config: Record<string, { label: string; class: string; icon: string }> = {
    elated: { label: '士氣高昂 (Elated)', class: 'mo-elated', icon: '🟢' },
    calm: { label: '神色自若 (Calm)', class: 'mo-calm', icon: '🔵' },
    neutral: { label: '心平氣和 (Neutral)', class: 'mo-neutral', icon: '⚪' },
    anxious: { label: '忐忑不安 (Anxious)', class: 'mo-anxious', icon: '🟡' },
    despair: { label: '徹底絕望 (Despair)', class: 'mo-despair', icon: '🔴' }
  }
  return config[level] || { label: level, class: 'mo-unknown', icon: '⚪' }
})

function formatDimension(dim: string | number): string {
  const dimStr = String(dim)
  const mapping: Record<string, string> = {
    caution: '謹慎度',
    empathy: '同理心',
    honor: '榮譽感',
    curiosity: '好奇心',
    violence: '暴力傾向'
  }
  return mapping[dimStr] || dimStr
}

function formatLevel(level: string | number): string {
  const levelStr = String(level)
  const mapping: Record<string, string> = {
    reckless: '魯莽', bold: '大膽', careful: '小心', timid: '膽怯',
    ruthless: '冷酷', pragmatic: '實用', compassionate: '同理', selfless: '無私',
    deceitful: '欺瞞', flexible: '靈活', honest: '誠實', righteous: '正直',
    indifferent: '冷漠', practical: '務實', curious: '好奇', obsessed: '狂熱',
    pacifist: '和平', defensive: '防衛', balanced: '平衡', aggressive: '侵略'
  }
  return mapping[levelStr] || levelStr
}
</script>

<template>
  <div class="character-status" v-if="state">
    <div class="status-card-header">
      <span class="role-icon">👤</span>
      <h3>{{ state.name }}</h3>
    </div>

    <!-- Physical state -->
    <div class="status-section">
      <h4>物理軀體 (Physical)</h4>
      <div class="status-row">
        <span class="label">體力狀態：</span>
        <div class="value-wrapper">
          <span class="led-dot" :class="staminaInfo.class"></span>
          <span class="value">{{ staminaInfo.label }}</span>
        </div>
      </div>
      <div class="status-row">
        <span class="label">健康程度：</span>
        <div class="value-wrapper">
          <span class="led-dot" :class="healthInfo.class"></span>
          <span class="value">{{ healthInfo.label }}</span>
        </div>
      </div>
      <div v-if="state.physical?.active_effects?.length" class="effects">
        <span class="effect-tag" v-for="effect in state.physical.active_effects" :key="effect">
          🩹 {{ effect }}
        </span>
      </div>
    </div>

    <!-- Mental state -->
    <div class="status-section">
      <h4>心智意識 (Mental)</h4>
      <div class="status-row">
        <span class="label">當前情緒：</span>
        <div class="value-wrapper">
          <span class="led-dot" :class="moraleInfo.class"></span>
          <span class="value">{{ moraleInfo.label }}</span>
        </div>
      </div>
      <div class="status-row">
        <span class="label">警覺程度：</span>
        <div class="value-wrapper">
          <span class="led-dot" :class="state.mental?.alertness_level === 'alert' ? 'mo-calm' : 'mo-neutral'"></span>
          <span class="value">{{ state.mental?.alertness_level === 'alert' ? '高度警惕 (Alert)' : '放鬆 (Relaxed)' }}</span>
        </div>
      </div>
    </div>

    <!-- HIDDEN 2026-06-08: attitude / 態度選擇 system disabled. To re-enable, restore the block below. -->
    <!--
    <div v-if="state.attitude" class="status-section">
      <h4>性格態度傾向 (Attitude)</h4>
      <div class="attitude-grid">
        <div v-for="(level, dim) in state.attitude" :key="dim" class="attitude-mini-card">
          <span class="att-name">{{ formatDimension(dim) }}</span>
          <span class="att-val">{{ formatLevel(level) }}</span>
        </div>
      </div>
    </div>
    -->
  </div>
</template>

<style scoped>
.character-status {
  background: var(--color-glass-bg);
  padding: 1.5rem;
  border-radius: var(--border-radius-m);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(12px);
}

.status-card-header {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  padding-bottom: 0.6rem;
  margin-bottom: 1rem;
}

.role-icon {
  font-size: 1.3rem;
  filter: drop-shadow(0 0 5px rgba(212, 175, 55, 0.3));
}

h3 {
  color: var(--color-accent);
  font-size: 1.15rem;
  margin: 0;
}

h4 {
  font-size: 0.82rem;
  margin: 1rem 0 0.5rem;
  opacity: 0.6;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-accent);
}

.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.45rem 0;
  font-size: 0.88rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.02);
}

.label {
  opacity: 0.75;
}

.value-wrapper {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.value {
  color: #fff;
  font-weight: 500;
}

/* LED Indicator Glows */
.led-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}

.st-fresh, .hl-healthy, .mo-elated {
  background: var(--color-success);
  box-shadow: 0 0 8px var(--color-success);
}
.st-breath, .mo-calm {
  background: #3498db;
  box-shadow: 0 0 8px #3498db;
}
.st-ache, .hl-wounded, .mo-anxious {
  background: var(--color-warning);
  box-shadow: 0 0 8px var(--color-warning);
}
.st-exhausted, .hl-severe {
  background: #e67e22;
  box-shadow: 0 0 8px #e67e22;
}
.st-collapse, .hl-dying, .mo-despair {
  background: var(--color-danger);
  box-shadow: 0 0 8px var(--color-danger);
}
.hl-dead {
  background: #555;
  box-shadow: none;
}
.hl-dying {
  animation: blink 0.8s infinite alternate;
}

@keyframes blink {
  from { opacity: 0.3; }
  to { opacity: 1; }
}

.effects {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.6rem;
}

.effect-tag {
  padding: 0.2rem 0.5rem;
  background: rgba(231, 76, 60, 0.12);
  border: 1px solid rgba(231, 76, 60, 0.3);
  color: #ff7675;
  border-radius: 4px;
  font-size: 0.75rem;
}

/* Personality Grid */
.attitude-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.attitude-mini-card {
  display: flex;
  flex-direction: column;
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid var(--color-glass-border);
  padding: 0.4rem 0.6rem;
  border-radius: var(--border-radius-s);
}

.att-name {
  font-size: 0.72rem;
  opacity: 0.5;
}

.att-val {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--color-accent);
}
</style>
