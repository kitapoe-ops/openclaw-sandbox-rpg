<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { gameApi } from '@/services/api'

const router = useRouter()
const characterName = ref('')
const selectedStarter = ref<string | null>(null)
const isCreating = ref(false)

const starters = [
  {
    id: 'char_starter_01',
    name: '艾德溫 — 退伍軍人 (Edwin)',
    role: '戰士 (Fighter)',
    description: '昔日長槍軍團的驍勇戰士，歷經深水城邊境戰役，如今一無所有。沉默內斂，右手雖佈滿厚繭與刀疤，出劍卻快如閃電。身懷極高防禦力，能從「slight_breath」迅速調息。'
  },
  {
    id: 'char_starter_02',
    name: '莉拉 — 神秘旅人 (Lila)',
    role: '遊俠 (Ranger)',
    description: '披著兜帽行蹤飄忽的斥候，通曉費倫大陸無數地精與紅印幫內情。性格冷靜機警，善用短弓與盜賊工具，能在危急關頭識破機關與陷阱，善於在陰影中潛行。'
  },
  {
    id: 'char_starter_03',
    name: '湯姆 — 年輕學徒 (Tom)',
    role: '法師 (Wizard)',
    description: '師從不冬城魔法學院的博學少年，隨身攜帶厚重的火系法術書。性格好奇且意志高昂，雖然體質偏弱，但能操縱防防法杖構築結界，對魔力殘留有著天然的敏銳感知。'
  }
]

async function createCharacter() {
  if (!characterName.value || !selectedStarter.value || isCreating.value) return
  isCreating.value = true
  try {
    const res = await gameApi.createCharacter({
      name: characterName.value,
      world_id: 'dnd_5e_forgotten_realms',
      starter_id: selectedStarter.value
    })
    router.push({ name: 'game', params: { characterId: res.character_id } })
  } catch (e) {
    console.error('Failed to create character:', e)
  } finally {
    isCreating.value = false
  }
}
</script>

<template>
  <div class="character-create-container">
    <div class="aurora-glow"></div>
    <div class="create-card">
      <h1>創建新角色</h1>
      <p class="subtitle">踏入被遺忘的國度，譜寫屬於你的冒險詩篇</p>

      <div class="form">
        <div class="input-group">
          <label for="char-name">你的傳奇姓名</label>
          <div class="input-wrapper">
            <input 
              id="char-name"
              v-model="characterName" 
              type="text" 
              placeholder="例如：Garrick Stonefist..." 
              required
              :disabled="isCreating"
            />
            <span class="focus-border"></span>
          </div>
        </div>

        <h2>選擇身世背景</h2>
        <div class="starters">
          <div
            v-for="starter in starters"
            :key="starter.id"
            class="starter-card"
            :class="{ selected: selectedStarter === starter.id, disabled: isCreating }"
            @click="selectedStarter = starter.id"
          >
            <div class="card-glow"></div>
            <span class="role-badge">{{ starter.role }}</span>
            <h3>{{ starter.name }}</h3>
            <p>{{ starter.description }}</p>
          </div>
        </div>

        <button
          @click="createCharacter"
          :disabled="!characterName || !selectedStarter || isCreating"
          class="create-btn"
        >
          <span class="btn-shine"></span>
          {{ isCreating ? '正在感應宿命...' : '開 始 旅 程' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.character-create-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 2rem 1.5rem;
  position: relative;
  overflow: hidden;
}

.aurora-glow {
  position: absolute;
  top: -10%;
  right: -10%;
  width: 120%;
  height: 120%;
  background: 
    radial-gradient(circle at 80% 20%, rgba(138, 43, 226, 0.12) 0%, transparent 40%),
    radial-gradient(circle at 20% 80%, rgba(212, 175, 55, 0.08) 0%, transparent 50%);
  filter: blur(80px);
  z-index: 1;
}

.create-card {
  position: relative;
  z-index: 10;
  width: 100%;
  max-width: 900px;
  background: var(--color-glass-bg);
  border: 1px solid var(--color-border);
  box-shadow: var(--color-glass-shadow);
  backdrop-filter: blur(16px);
  border-radius: var(--border-radius-m);
  padding: 2.5rem;
  animation: fade-in-up 0.6s ease-out;
}

@keyframes fade-in-up {
  from { opacity: 0; transform: translateY(15px); }
  to { opacity: 1; transform: translateY(0); }
}

h1 {
  font-size: 2.2rem;
  color: var(--color-accent);
  text-align: center;
  margin-bottom: 0.3rem;
}

.subtitle {
  text-align: center;
  color: var(--color-text-muted);
  font-size: 0.9rem;
  margin-bottom: 2rem;
  font-style: italic;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.input-group label {
  font-size: 0.95rem;
  font-weight: 500;
  color: var(--color-accent);
  letter-spacing: 0.05em;
}

.input-wrapper {
  position: relative;
  width: 100%;
}

input {
  display: block;
  width: 100%;
  padding: 0.9rem 1.2rem;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-s);
  color: var(--color-text);
  font-size: 1rem;
  font-family: var(--font-body);
  transition: var(--transition-smooth);
}

input:focus {
  outline: none;
  border-color: var(--color-accent);
  background: rgba(0, 0, 0, 0.6);
  box-shadow: var(--shadow-glow);
}

.starters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1.2rem;
  margin-bottom: 1rem;
}

h2 {
  font-size: 1.2rem;
  color: var(--color-accent);
  border-left: 3px solid var(--color-accent);
  padding-left: 0.5rem;
  margin: 0.5rem 0;
}

.starter-card {
  position: relative;
  background: rgba(0, 0, 0, 0.35);
  padding: 1.5rem;
  border: 1px solid var(--color-glass-border);
  border-radius: var(--border-radius-m);
  cursor: pointer;
  transition: var(--transition-smooth);
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  overflow: hidden;
}

.starter-card:hover:not(.disabled) {
  border-color: rgba(212, 175, 55, 0.5);
  background: rgba(18, 13, 36, 0.55);
  transform: translateY(-3px);
}

.starter-card.selected {
  border-color: var(--color-accent);
  background: rgba(212, 175, 55, 0.07);
  box-shadow: var(--shadow-glow);
}

.role-badge {
  align-self: flex-start;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.25rem 0.6rem;
  background: rgba(212, 175, 55, 0.15);
  border: 1px solid rgba(212, 175, 55, 0.3);
  color: var(--color-accent);
  border-radius: 20px;
  text-transform: uppercase;
}

.starter-card h3 {
  font-size: 1.05rem;
  color: #fff;
  transition: var(--transition-smooth);
}

.starter-card.selected h3 {
  color: var(--color-accent);
}

.starter-card p {
  font-size: 0.85rem;
  color: var(--color-text-muted);
  line-height: 1.6;
  flex-grow: 1;
}

.starter-card.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Shimmer Button styles */
.create-btn {
  position: relative;
  width: 100%;
  padding: 1.1rem;
  background: linear-gradient(135deg, var(--color-accent) 0%, #a38120 100%);
  color: #07050d;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: var(--border-radius-s);
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(212, 175, 55, 0.25);
  transition: var(--transition-smooth);
  overflow: hidden;
  margin-top: 1rem;
}

.create-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(212, 175, 55, 0.4);
}

.create-btn:active:not(:disabled) {
  transform: translateY(1px);
}

.create-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  box-shadow: none;
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
    rgba(255, 255, 255, 0.35) 50%,
    rgba(255, 255, 255, 0) 100%
  );
  transform: skewX(-25deg);
  animation: shine 3.5s infinite;
}

@keyframes shine {
  0% { left: -100%; }
  35%, 100% { left: 150%; }
}
</style>
