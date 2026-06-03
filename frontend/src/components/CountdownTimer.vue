<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  remainingSeconds: number
}>()

const minutes = computed(() => Math.floor(props.remainingSeconds / 60))
const seconds = computed(() => props.remainingSeconds % 60)
const display = computed(() =>
  `${String(minutes.value).padStart(2, '0')}:${String(seconds.value).padStart(2, '0')}`
)
const isUrgent = computed(() => props.remainingSeconds < 60 && props.remainingSeconds > 0)
const isExpired = computed(() => props.remainingSeconds === 0)
</script>

<template>
  <div
    class="countdown-timer"
    :class="{ urgent: isUrgent, expired: isExpired }"
  >
    <div class="label">{{ isExpired ? '已超時' : '本輪剩餘' }}</div>
    <div class="time">{{ display }}</div>
    <div v-if="isExpired" class="warning">
      角色將進入 NPC 自動行為
    </div>
  </div>
</template>

<style scoped>
.countdown-timer {
  background: rgba(255, 255, 255, 0.05);
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid var(--color-border);
  text-align: center;
}

.countdown-timer.urgent {
  border-color: #ff6b6b;
  animation: pulse 1s infinite;
}

.countdown-timer.expired {
  border-color: #ff0000;
  background: rgba(255, 0, 0, 0.1);
}

.label {
  font-size: 0.8rem;
  opacity: 0.7;
  margin-bottom: 0.3rem;
}

.time {
  font-size: 1.8rem;
  font-weight: bold;
  color: var(--color-accent);
  font-variant-numeric: tabular-nums;
}

.urgent .time {
  color: #ff6b6b;
}

.expired .time {
  color: #ff0000;
}

.warning {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #ff6b6b;
  font-weight: 500;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
