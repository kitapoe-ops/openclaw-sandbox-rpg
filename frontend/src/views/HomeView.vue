<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { gameApi } from '@/services/api'

const router = useRouter()
const characters = ref<any[]>([])
const isLoading = ref(false)
const showPasswordModal = ref(false)
const selectedCharId = ref<string | null>(null)
const selectedCharName = ref('')
const loginPassword = ref('')
const loginError = ref('')
const isVerifying = ref(false)

async function fetchCharacters() {
  isLoading.value = true
  try {
    characters.value = await gameApi.listCharacters()
  } catch (e) {
    console.error('Failed to fetch characters:', e)
  } finally {
    isLoading.value = false
  }
}

onMounted(() => {
  fetchCharacters()
})

function startNewGame() {
  if (characters.value.length >= 4) return
  router.push({ name: 'character-create' })
}

function promptPassword(charId: string, charName: string) {
  selectedCharId.value = charId
  selectedCharName.value = charName
  loginPassword.value = ''
  loginError.value = ''
  showPasswordModal.value = true
}

async function loginCharacter() {
  if (!selectedCharId.value || isVerifying.value) return
  isVerifying.value = true
  loginError.value = ''
  try {
    const success = await gameApi.verifyPassword(selectedCharId.value, loginPassword.value)
    if (success) {
      showPasswordModal.value = false
      router.push({ name: 'game', params: { characterId: selectedCharId.value } })
    } else {
      loginError.value = '密碼錯誤，請重新輸入'
    }
  } catch (e: any) {
    loginError.value = e?.message || '驗證失敗'
  } finally {
    isVerifying.value = false
  }
}

function formatStarter(starterId: string): string {
  const mapping: Record<string, string> = {
    char_starter_01: '戰士 - 艾德溫',
    char_starter_02: '遊俠 - 莉拉',
    char_starter_03: '法師 - 湯姆'
  }
  return mapping[starterId] || starterId
}

const isResetting = ref(false)
const resetError = ref('')

async function handleResetWorld() {
  if (!confirm('您確定要重置世界嗎？這將會刪除所有玩家創建的角色及遊戲歷史！')) return
  isResetting.value = true
  resetError.value = ''
  try {
    const success = await gameApi.resetCharacters()
    if (success) {
      alert('重置成功！')
      // 清空本地 localStorage 緩存
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (key && (key.startsWith('openclaw_') || key.startsWith('custom_char_'))) {
          localStorage.removeItem(key)
        }
      }
      await fetchCharacters()
    } else {
      resetError.value = '重置失敗，請稍後再試'
    }
  } catch (e: any) {
    resetError.value = e?.message || '重置出錯'
  } finally {
    isResetting.value = false
  }
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

        <!-- Existing characters list -->
        <section class="char-list-section" v-if="characters.length > 0">
          <h3>選擇已有角色</h3>
          <div class="char-grid">
            <div 
              v-for="char in characters" 
              :key="char.character_id" 
              class="char-item-card"
              @click="promptPassword(char.character_id, char.name)"
            >
              <div class="char-info">
                <span class="char-avatar">👤</span>
                <div class="char-meta">
                  <span class="char-name">{{ char.name }}</span>
                  <span class="char-starter">{{ formatStarter(char.starter_id) }}</span>
                </div>
              </div>
              <button class="char-select-btn">冒險</button>
            </div>
          </div>
        </section>

        <div class="btn-container">
          <button 
            @click="startNewGame" 
            class="start-btn" 
            :class="{ disabled: characters.length >= 4 }"
            :disabled="characters.length >= 4"
          >
            <span class="btn-shine"></span>
            {{ characters.length >= 4 ? '角色已達 4 人上限' : '開始新旅程' }}
          </button>
          <p class="limit-hint" v-if="characters.length >= 4">最多支援 4 個玩家角色，可直接選擇上述角色開始冒險。</p>
          
          <button 
            @click="handleResetWorld" 
            class="reset-world-btn"
            :disabled="isResetting"
          >
            {{ isResetting ? '正在重置世界...' : '重置世界與角色' }}
          </button>
          <p class="reset-error-msg" v-if="resetError">⚠️ {{ resetError }}</p>
        </div>
      </main>
    </div>

    <!-- Password Modal -->
    <div class="modal-overlay" v-if="showPasswordModal" @click.self="showPasswordModal = false">
      <div class="modal-content">
        <h3>存取角色：{{ selectedCharName }}</h3>
        <p class="modal-hint">請輸入此角色的存取密碼以繼續冒險：</p>
        <div class="input-group">
          <input 
            type="password" 
            v-model="loginPassword" 
            placeholder="請輸入密碼..." 
            @keyup.enter="loginCharacter"
            required
          />
        </div>
        <p class="modal-error" v-if="loginError">⚠️ {{ loginError }}</p>
        <div class="modal-actions">
          <button class="modal-btn cancel" @click="showPasswordModal = false">取消</button>
          <button class="modal-btn confirm" :disabled="isVerifying" @click="loginCharacter">
            {{ isVerifying ? '驗證中...' : '進入遊戲' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Existing Characters Styling */
.char-list-section {
  margin-bottom: 2rem;
  text-align: left;
}

.char-list-section h3 {
  font-size: 1.1rem;
  color: var(--color-accent);
  margin-bottom: 1rem;
  border-left: 3px solid var(--color-accent);
  padding-left: 0.5rem;
}

.char-grid {
  display: flex;
  flex-direction: column;
  gap: 0.8rem;
}

.char-item-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.8rem 1.2rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-s);
  cursor: pointer;
  transition: var(--transition-smooth);
}

.char-item-card:hover {
  border-color: var(--color-accent);
  background: rgba(212, 175, 55, 0.05);
}

.char-info {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.char-avatar {
  font-size: 1.5rem;
}

.char-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.char-name {
  color: #fff;
  font-weight: 600;
  font-size: 1rem;
}

.char-starter {
  color: var(--color-text-muted);
  font-size: 0.8rem;
}

.char-select-btn {
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

.char-item-card:hover .char-select-btn {
  background: var(--color-accent);
  color: #07050d;
}

.start-btn.disabled {
  opacity: 0.5;
  cursor: not-allowed;
  background: #333 !important;
  color: #888 !important;
  box-shadow: none !important;
}

.limit-hint {
  font-size: 0.8rem;
  color: #ff4d4d;
  margin-top: 0.5rem;
  font-style: italic;
}

/* Modal Styling */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  width: 100vw;
  height: 100vh;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  backdrop-filter: blur(4px);
}

.modal-content {
  background: rgba(18, 13, 36, 0.95);
  border: 1px solid var(--color-accent);
  border-radius: var(--border-radius-m);
  padding: 2rem;
  width: 90%;
  max-width: 400px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
  text-align: left;
}

.modal-content h3 {
  color: var(--color-accent);
  margin-bottom: 0.5rem;
  font-size: 1.25rem;
}

.modal-hint {
  color: var(--color-text-muted);
  font-size: 0.9rem;
  margin-bottom: 1.2rem;
}

.modal-content input {
  width: 100%;
  padding: 0.8rem;
  background: rgba(0, 0, 0, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #fff;
  border-radius: var(--border-radius-s);
  font-size: 1rem;
  margin-bottom: 1rem;
}

.modal-content input:focus {
  outline: none;
  border-color: var(--color-accent);
}

.modal-error {
  color: #ff4d4d;
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 1rem;
}

.modal-btn {
  padding: 0.5rem 1.2rem;
  border-radius: var(--border-radius-s);
  font-weight: 600;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.modal-btn.cancel {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: var(--color-text-muted);
}

.modal-btn.cancel:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #fff;
}

.modal-btn.confirm {
  background: var(--color-accent);
  border: none;
  color: #07050d;
}

.modal-btn.confirm:hover:not(:disabled) {
  background: var(--color-accent-hover);
}

.modal-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

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

.start-btn:hover:not(.disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(212, 175, 55, 0.5);
  background: linear-gradient(135deg, var(--color-accent-hover) 0%, var(--color-accent) 100%);
}

.start-btn:active:not(.disabled) {
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

.reset-world-btn {
  display: block;
  width: 100%;
  max-width: 280px;
  margin: 1.2rem auto 0;
  padding: 0.8rem 1.5rem;
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  background: rgba(231, 76, 60, 0.15);
  border: 1px solid rgba(231, 76, 60, 0.35);
  color: #ff4d4d;
  border-radius: var(--border-radius-s);
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(231, 76, 60, 0.1);
  backdrop-filter: blur(8px);
  transition: var(--transition-smooth);
}

.reset-world-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  background: rgba(231, 76, 60, 0.25);
  border-color: rgba(231, 76, 60, 0.5);
  box-shadow: 0 6px 20px rgba(231, 76, 60, 0.25);
}

.reset-world-btn:active:not(:disabled) {
  transform: translateY(1px);
}

.reset-world-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.reset-error-msg {
  color: #ff4d4d;
  font-size: 0.85rem;
  margin-top: 0.5rem;
  font-style: italic;
}
</style>
