<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()

function startGame() {
  router.push({ name: 'character-create' })
}
</script>

<template>
  <div class="home">
    <header>
      <h1>OpenClaw Sandbox RPG</h1>
      <p class="tagline">異步多人純語意狀態機沙盒劇本世界</p>
    </header>

    <main>
      <section class="intro">
        <h2>歡迎</h2>
        <p>一個基於 D&amp;D 5e 世界觀嘅異步多人 RPG。</p>
        <p>純語意狀態，無數字；每 15 分鐘一個回合。</p>
      </section>

      <button @click="startGame" class="start-btn">
        開始新旅程
      </button>
    </main>
  </div>
</template>

<style scoped>
.home {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
}

header {
  text-align: center;
  margin-bottom: 3rem;
}

h1 {
  font-size: 2.5rem;
  color: var(--color-accent);
  margin-bottom: 0.5rem;
}

.tagline {
  color: var(--color-text);
  opacity: 0.7;
}

.intro {
  background: rgba(255, 255, 255, 0.05);
  padding: 2rem;
  border-radius: 8px;
  margin-bottom: 2rem;
}

.start-btn {
  display: block;
  width: 100%;
  max-width: 300px;
  margin: 0 auto;
  padding: 1rem 2rem;
  font-size: 1.1rem;
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  transition: opacity 0.2s;
}

.start-btn:hover {
  opacity: 0.85;
}
</style>
