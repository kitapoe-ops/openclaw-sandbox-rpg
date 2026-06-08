<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function startGame() {
  router.push({ name: 'character-create' })
}
</script>

<template>
  <div class="home-container">
    <div class="aurora-glow"></div>
    <div class="home-card">
      <header>
        <div class="logo-shield">🛡️</div>
        <h1>OpenClaw Sandbox RPG</h1>
        <p class="tagline">異步多人純語意狀態機沙盒劇本世界</p>
      </header>

      <main>
        <section class="intro">
          <h2>冒險啟程</h2>
          <p>
            歡迎踏入基於 <strong>D&amp;D 5e 被遺忘的國度</strong> 世界觀的異步多人開放沙盒 RPG。
          </p>
          <p>
            這裡摒棄了死板的生命值與法力值數字，取而代之的是<strong>純語意階梯狀態機</strong>。
            你的每一次抉擇與心態，都將深刻塑造你在費倫大陸的傳奇故事。
          </p>
        </section>

        <button @click="startGame" class="start-btn">
          <span class="btn-shine"></span>
          開始新旅程
        </button>
      </main>
    </div>
  </div>
</template>

<style scoped>
.home-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 1.5rem;
  position: relative;
  overflow: hidden;
}

/* Dynamic Aurora Background */
.aurora-glow {
  position: absolute;
  top: -20%;
  left: -20%;
  width: 140%;
  height: 140%;
  background: 
    radial-gradient(circle at 30% 20%, rgba(212, 175, 55, 0.08) 0%, transparent 40%),
    radial-gradient(circle at 70% 60%, rgba(138, 43, 226, 0.15) 0%, transparent 50%),
    radial-gradient(circle at 10% 80%, rgba(72, 61, 139, 0.12) 0%, transparent 40%);
  filter: blur(80px);
  z-index: 1;
  animation: aurora-move 20s infinite alternate ease-in-out;
}

@keyframes aurora-move {
  0% { transform: translate(0, 0) rotate(0deg); }
  50% { transform: translate(-5%, 5%) rotate(5deg); }
  100% { transform: translate(5%, -5%) rotate(-5deg); }
}

.home-card {
  position: relative;
  z-index: 10;
  width: 100%;
  max-width: 680px;
  background: var(--color-glass-bg);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(16px);
  border-radius: var(--border-radius-m);
  padding: 3rem 2rem;
  text-align: center;
  animation: fade-in-up 0.8s ease-out;
}

@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(20px); }
  to { opacity: 1; transform: translateY(0); }
}

.logo-shield {
  font-size: 3.5rem;
  margin-bottom: 1rem;
  filter: drop-shadow(0 0 10px rgba(212, 175, 55, 0.4));
  animation: pulse-glow 3s infinite ease-in-out;
}

@keyframes pulse-glow {
  0%, 100% { filter: drop-shadow(0 0 8px rgba(212, 175, 55, 0.3)); transform: scale(1); }
  50% { filter: drop-shadow(0 0 18px rgba(212, 175, 55, 0.6)); transform: scale(1.05); }
}

h1 {
  font-size: 2.4rem;
  background: linear-gradient(135deg, #fff 30%, var(--color-accent) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 0.5rem;
}

.tagline {
  color: var(--color-text-muted);
  font-size: 0.95rem;
  letter-spacing: 0.1em;
  margin-bottom: 2.5rem;
}

.intro {
  text-align: left;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.03);
  padding: 1.8rem;
  border-radius: var(--border-radius-m);
  margin-bottom: 2.5rem;
}

.intro h2 {
  font-size: 1.25rem;
  color: var(--color-accent);
  margin-bottom: 1rem;
  border-left: 3px solid var(--color-accent);
  padding-left: 0.6rem;
}

.intro p {
  font-size: 0.95rem;
  margin-bottom: 1rem;
  opacity: 0.85;
  line-height: 1.7;
}

.intro p:last-child {
  margin-bottom: 0;
}

/* Premium Shimmer Button */
.start-btn {
  position: relative;
  display: block;
  width: 100%;
  max-width: 280px;
  margin: 0 auto;
  padding: 1rem 2rem;
  font-size: 1.1rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  background: linear-gradient(135deg, var(--color-accent) 0%, #a38120 100%);
  color: #07050d;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: var(--border-radius-s);
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(212, 175, 55, 0.3);
  transition: var(--transition-smooth);
  overflow: hidden;
}

.start-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(212, 175, 55, 0.5);
  background: linear-gradient(135deg, var(--color-accent-hover) 0%, var(--color-accent) 100%);
}

.start-btn:active {
  transform: translateY(1px);
}

.btn-shine {
  position: absolute;
  top: 0;
  left: -100%;
  width: 50%;
  height: 100%;
  background: linear-gradient(
    to right,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.3) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  transform: skewX(-25deg);
  animation: shine 4s infinite;
}

@keyframes shine {
  0% { left: -100%; }
  30%, 100% { left: 150%; }
}
</style>
