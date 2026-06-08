<script setup lang="ts">
import { onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useGameStore } from '@/stores/gameStore'
import { gameApi } from '@/services/api'
import ScenePanel from '@/components/ScenePanel.vue'
import ChoiceCard from '@/components/ChoiceCard.vue'
import CharacterStatus from '@/components/CharacterStatus.vue'
import Inventory from '@/components/Inventory.vue'
import Equipment from '@/components/Equipment.vue'
import HistoryLog from '@/components/HistoryLog.vue'
import OtherPlayersPanel from '@/components/OtherPlayersPanel.vue'

const route = useRoute()
const router = useRouter()
const gameStore = useGameStore()
const characterId = route.params.characterId as string
const setLoadError = gameStore.setLoadError
const setCharacterState = gameStore.setCharacterState
const setCurrentScene = gameStore.setCurrentScene

onMounted(async () => {
  if (characterId.startsWith('player_char_')) {
    const pwd = localStorage.getItem(`openclaw_pwd_${characterId}`)
    if (!pwd) {
      setLoadError('無角色存取權限。請返回首頁並輸入密碼以進行冒險。')
      setTimeout(() => {
        router.push('/')
      }, 2500)
      return
    }
  }

  let state: any = null
  let scene: any = null
  const timeout = setTimeout(() => {
    setLoadError(
      '載入逾時（25秒）— 請重新整理或確認網路連線。\n' +
      '  角色 ID: ' + characterId
    )
  }, 25000)
  try {
    state = await gameApi.getCharacter(characterId)
    setCharacterState(state)
  } catch (e: any) {
    clearTimeout(timeout)
    if (e?.response?.status === 404 || /not found/i.test(String(e?.message || e))) {
      setLoadError(`角色 '${characterId}' 不存在。請重新創建新角色。`)
      return
    }
    console.error('Failed to load character state:', e)
    setLoadError(`Failed to load character: ${e?.message || e}`)
    return
  }

  try {
    scene = await gameApi.getCurrentScene(characterId)
    setCurrentScene(scene)
  } catch (e) {
    console.error('Failed to load current scene:', e)
  }

  try {
    await gameStore.initialize(characterId)
    clearTimeout(timeout)
  } catch (e: any) {
    clearTimeout(timeout)
    console.error('Failed to initialize game store:', e)
    setLoadError(
      '後端連線失敗: ' + (e?.message || e) + '\n\n' +
      '請確認後端伺服器（port 8000）是否正常運行。'
    )
  }
})

onUnmounted(() => {
  gameStore.cleanup()
})

const isMobile = computed(() => {
  if (typeof window === 'undefined') return false
  return window.innerWidth < 1024
})

async function handleChoice(payload: { optionId: string; attitudeSelections: any[] }) {
  gameStore.submitChoice(payload.optionId, payload.attitudeSelections)
}
</script>

<template>
  <div class="game-view-wrapper">
    <!-- Top Navigation Bar -->
    <nav class="game-navbar">
      <div class="nav-brand" @click="$router.push('/')">
        <span class="nav-icon">🛡️</span>
        <span class="nav-title">OpenClaw RPG</span>
      </div>
      <div class="nav-world">
        🌍 被遺忘嘅國度 · 凡達林
      </div>
      <div class="nav-right">
        <div class="connection-status" :class="{ connected: gameStore.isConnected }">
          <span class="status-dot"></span>
          {{ gameStore.isConnected ? '已連線' : '中斷連線' }}
          <span v-if="gameStore.isReclaiming" class="reclaim-tag">(重連中...)</span>
        </div>
        <button class="home-btn" @click="$router.push('/')">返主頁</button>
      </div>
    </nav>

    <div class="game-view" :class="{ mobile: isMobile }">
      <!-- Surface load errors to the user -->
      <div v-if="gameStore.loadError" class="load-error-banner">
        <span class="error-icon">⚠️</span>
        <div class="error-msg">
          <p>{{ gameStore.loadError }}</p>
        </div>
        <button class="error-back-btn" @click="$router.push('/')">返主頁</button>
      </div>

      <!-- Surface task processing errors to the user -->
      <div v-if="gameStore.lastTaskError" class="load-error-banner processing-error">
        <span class="error-icon">⚠️</span>
        <div class="error-msg">
          <p>行動處理失敗：{{ gameStore.lastTaskError }}</p>
        </div>
        <button class="error-back-btn" @click="gameStore.clearTaskError()">清除錯誤</button>
      </div>

      <div class="left-panel">
        <!-- Story Scene Panel -->
        <ScenePanel :scene="gameStore.currentScene" />

        <!-- 4 Choice Cards arranged in responsive grid -->
        <div class="choices-container">
          <h3 class="choices-title">命運抉擇</h3>
          <p class="choices-hint">四個故事方向代表四種冒險宿命。請依直覺或角色設定做出選擇。</p>

          <div class="choices-grid">
            <ChoiceCard
              v-for="choice in gameStore.currentScene?.choices"
              :key="choice.id"
              :choice="choice"
              :disabled="gameStore.isProcessing"
              @select="(payload) => handleChoice(payload)"
            />
          </div>
        </div>
      </div>

      <div class="right-panel">
        <CharacterStatus
          v-if="gameStore.characterState"
          :state="gameStore.characterState"
        />

        <!-- HIDDEN 2026-06-08: items / equipment system disabled. To re-enable, restore the two mounts below. -->
        <!--
        <Equipment
          v-if="gameStore.characterState?.inventory.equipment"
          :equipment="gameStore.characterState.inventory.equipment"
        />

        <Inventory
          v-if="gameStore.characterState?.inventory.items"
          :items="gameStore.characterState.inventory.items"
        />
        -->

        <HistoryLog :history="gameStore.history" />

        <OtherPlayersPanel :actions="gameStore.otherPlayerActions" />

        <!-- State mismatch warning -->
        <div v-if="gameStore.stateMismatchWarning" class="state-mismatch-warning">
          <span>⚠️ 場景狀態已過期，已自動重新整理</span>
          <button @click="gameStore.clearStateMismatch">知道了</button>
        </div>

        <!-- Interrupted action notice -->
        <div v-if="gameStore.lastActionInterrupted" class="interrupted-notice">
          <span>⚠️ 上一個行動因伺服器重啟而被中斷，請重新選擇</span>
          <button @click="gameStore.lastActionInterrupted = false">知道了</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.game-view-wrapper {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background: var(--color-bg);
}

/* Premium Navbar */
.game-navbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 2rem;
  background: rgba(18, 13, 36, 0.85);
  border-bottom: 1px solid var(--color-border);
  backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.nav-brand:hover {
  opacity: 0.85;
}

.nav-icon {
  font-size: 1.5rem;
  filter: drop-shadow(0 0 5px rgba(212, 175, 55, 0.4));
}

.nav-title {
  font-family: var(--font-title);
  font-weight: 700;
  font-size: 1.25rem;
  color: var(--color-accent);
}

.nav-world {
  font-size: 0.85rem;
  color: var(--color-text-muted);
  letter-spacing: 0.05em;
  background: rgba(255, 255, 255, 0.03);
  padding: 0.3rem 0.8rem;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.nav-right {
  display: flex;
  align-items: center;
  gap: 1.2rem;
}

.connection-status {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--color-danger);
  background: rgba(231, 76, 60, 0.1);
  padding: 0.25rem 0.75rem;
  border-radius: 12px;
  border: 1px solid rgba(231, 76, 60, 0.25);
}

.connection-status.connected {
  color: var(--color-success);
  background: rgba(46, 204, 113, 0.1);
  border-color: rgba(46, 204, 113, 0.25);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: currentColor;
  box-shadow: 0 0 8px currentColor;
}

.reclaim-tag {
  font-size: 0.75rem;
  opacity: 0.7;
  font-style: italic;
}

.home-btn {
  padding: 0.35rem 0.8rem;
  background: transparent;
  border: 1px solid var(--color-accent);
  color: var(--color-accent);
  border-radius: var(--border-radius-s);
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.home-btn:hover {
  background: var(--color-accent);
  color: #07050d;
}

/* View Grid Layout */
.game-view {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 1.5rem;
  padding: 1.5rem;
  max-width: 1600px;
  width: 100%;
  margin: 0 auto;
  flex-grow: 1;
}

.left-panel,
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 1.2rem;
}

.choices-container {
  background: var(--color-glass-bg);
  padding: 1.8rem;
  border-radius: var(--border-radius-m);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(12px);
}

.choices-title {
  color: var(--color-accent);
  margin-bottom: 0.3rem;
  font-size: 1.2rem;
  border-left: 3px solid var(--color-accent);
  padding-left: 0.5rem;
}

.choices-hint {
  font-size: 0.82rem;
  color: var(--color-text-muted);
  margin-bottom: 1.2rem;
  font-style: italic;
}

.choices-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1.2rem;
}

/* Load error banner */
.load-error-banner {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 1rem;
  background: rgba(231, 76, 60, 0.15);
  border: 1px solid rgba(231, 76, 60, 0.4);
  padding: 1rem 1.5rem;
  border-radius: var(--border-radius-m);
  color: #fff;
  backdrop-filter: blur(8px);
}

.error-icon {
  font-size: 1.5rem;
}

.error-msg {
  flex-grow: 1;
  font-size: 0.95rem;
  line-height: 1.5;
}

.error-back-btn {
  padding: 0.5rem 1rem;
  background: var(--color-danger);
  border: none;
  color: #fff;
  border-radius: var(--border-radius-s);
  cursor: pointer;
  font-weight: 600;
  transition: var(--transition-smooth);
}

.error-back-btn:hover {
  opacity: 0.9;
}

.state-mismatch-warning,
.interrupted-notice {
  padding: 0.8rem 1rem;
  background: rgba(241, 196, 15, 0.12);
  border: 1px solid rgba(241, 196, 15, 0.4);
  border-radius: var(--border-radius-m);
  font-size: 0.85rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  color: #fff;
}

.state-mismatch-warning button,
.interrupted-notice button {
  padding: 0.25rem 0.6rem;
  background: rgba(241, 196, 15, 0.2);
  border: 1px solid rgba(241, 196, 15, 0.5);
  color: var(--color-warning);
  border-radius: var(--border-radius-s);
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  transition: var(--transition-smooth);
}

.state-mismatch-warning button:hover,
.interrupted-notice button:hover {
  background: rgba(241, 196, 15, 0.35);
}

/* Mobile responsive styles */
.game-view.mobile .choices-grid {
  grid-template-columns: 1fr;
}

@media (max-width: 1024px) {
  .game-view {
    grid-template-columns: 1fr;
  }
}
</style>
