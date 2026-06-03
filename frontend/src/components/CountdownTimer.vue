<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'

const props = defineProps<{
  roundDuration: number  // minutes
}>()

const remainingSeconds = ref(props.roundDuration * 60)
let intervalId: number | undefined

onMounted(() => {
  intervalId = window.setInterval(() => {
    if (remainingSeconds.value > 0) {
      remainingSeconds.value--
    }
  }, 1000)
})

onUnmounted(() => {
  if (intervalId) clearInterval(intervalId)
})

const minutes = computed(() => Math.floor(remainingSeconds.value / 60))
const seconds = computed(() => remainingSeconds.value % 60)
const display = computed(() =>
  `${String(minutes.value).padStart(2, '0')}:${String(seconds.value).padStart(2, '0')}`
)
const isUrgent = computed(() => remainingSeconds.value < 60)
</script>

<template>
  <div class="countdown-timer" :class="{ urgent: isUrgent }">
    <div class="label">本輪剩餘</div>
    <div class="time">{{ display }}</div>
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

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}
</style>
