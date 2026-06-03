<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const characterName = ref('')
const selectedStarter = ref<string | null>(null)

const starters = [
  {
    id: 'char_starter_01',
    name: '艾德溫 — 退伍軍人',
    description: '曾經嘅王國士兵，戰後失去一切。沉默寡言，但有一雙見過死亡嘅眼。'
  },
  {
    id: 'char_starter_02',
    name: '莉拉 — 神秘旅人',
    description: '無人知佢從邊度嚟。知道好多秘密，但從不輕易透露。'
  },
  {
    id: 'char_starter_03',
    name: '湯姆 — 年輕學徒',
    description: '充滿熱誠嘅新手魔法師，滿腦子都係書本上嘅知識。'
  }
]

function createCharacter() {
  if (!characterName.value || !selectedStarter.value) return
  // TODO: Call API to create character
  router.push({ name: 'game', params: { characterId: 'new_character_id' } })
}
</script>

<template>
  <div class="character-create">
    <h1>創建角色</h1>

    <div class="form">
      <label>
        角色名稱
        <input v-model="characterName" type="text" placeholder="輸入你嘅名字" />
      </label>

      <h2>選擇起始角色</h2>
      <div class="starters">
        <div
          v-for="starter in starters"
          :key="starter.id"
          class="starter-card"
          :class="{ selected: selectedStarter === starter.id }"
          @click="selectedStarter = starter.id"
        >
          <h3>{{ starter.name }}</h3>
          <p>{{ starter.description }}</p>
        </div>
      </div>

      <button
        @click="createCharacter"
        :disabled="!characterName || !selectedStarter"
        class="create-btn"
      >
        開始旅程
      </button>
    </div>
  </div>
</template>

<style scoped>
.character-create {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem;
}

h1 {
  color: var(--color-accent);
  margin-bottom: 2rem;
  text-align: center;
}

.form {
  background: rgba(255, 255, 255, 0.05);
  padding: 2rem;
  border-radius: 8px;
}

label {
  display: block;
  margin-bottom: 1.5rem;
}

input {
  display: block;
  width: 100%;
  margin-top: 0.5rem;
  padding: 0.75rem;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--color-border);
  border-radius: 4px;
  color: var(--color-text);
  font-size: 1rem;
}

.starters {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.starter-card {
  background: rgba(0, 0, 0, 0.3);
  padding: 1.5rem;
  border: 2px solid var(--color-border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.starter-card:hover {
  border-color: var(--color-accent);
}

.starter-card.selected {
  border-color: var(--color-accent);
  background: rgba(183, 141, 74, 0.1);
}

.starter-card h3 {
  color: var(--color-accent);
  margin-bottom: 0.5rem;
}

.create-btn {
  width: 100%;
  padding: 1rem;
  background: var(--color-accent);
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 1.1rem;
  cursor: pointer;
}

.create-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
