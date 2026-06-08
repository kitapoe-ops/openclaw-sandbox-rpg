<script setup lang="ts">
/**
 * Prompt Inspector Panel (2026-06-08)
 * ===================================
 * Read-only dev tool that displays the LLM system prompt the PromptBuilder
 * would construct for the current character. Renders inside a collapsible
 * <details> element so it can stay open during gameplay for quick reference.
 *
 * Behaviour:
 * - On mount, calls GET /api/prompt-inspector/health. If the response says
 *   enabled=false, the panel is not rendered (returns null).
 * - If enabled, on every character change, calls GET /api/prompt-inspector/preview
 *   and renders the system prompt + section breakdown in a <pre> block.
 * - This panel is READ-ONLY. There is no edit field, no submit button, no
 *   audit bypass. The endpoint does not call the LLM, does not write the
 *   DB, and never touches R1-14B.
 */
import { ref, watch, onMounted } from 'vue'
import { useGameStore } from '@/stores/gameStore'

const gameStore = useGameStore()
const enabled = ref<boolean>(false)
const loading = ref<boolean>(false)
const error = ref<string | null>(null)
const data = ref<any | null>(null)
const isExpanded = ref<boolean>(false)
const activeTab = ref<'full' | 'sections' | 'flags'>('full')

async function checkHealth() {
  try {
    const resp = await fetch('/api/prompt-inspector/health')
    if (!resp.ok) {
      enabled.value = false
      return
    }
    const json = await resp.json()
    enabled.value = !!json.enabled
  } catch (e) {
    // Backend unreachable or CORS: assume disabled, do not render.
    enabled.value = false
  }
}

async function loadPreview() {
  if (!enabled.value) return
  const charId = gameStore.characterId || gameStore.characterState?.character_id || 'preview'
  loading.value = true
  error.value = null
  try {
    const resp = await fetch(`/api/prompt-inspector/preview?character_id=${encodeURIComponent(charId)}`)
    if (resp.status === 404) {
      error.value = 'Inspector disabled (flag off)'
      data.value = null
      return
    }
    if (!resp.ok) {
      error.value = `HTTP ${resp.status}`
      data.value = null
      return
    }
    data.value = await resp.json()
  } catch (e: any) {
    error.value = e?.message || 'Network error'
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await checkHealth()
  if (enabled.value) {
    await loadPreview()
  }
})

// Reload preview when the active character changes
watch(
  () => gameStore.characterId,
  async (newId) => {
    if (enabled.value && newId) {
      await loadPreview()
    }
  }
)
</script>

<template>
  <!-- Render nothing if the dev flag is off. Production users never see this. -->
  <div v-if="enabled" class="prompt-inspector-panel">
    <details class="inspector-details" :open="isExpanded" @toggle="isExpanded = ($event.target as HTMLDetailsElement).open">
      <summary class="inspector-summary">
        <span class="summary-arrow">🛠</span>
        Prompt Inspector (dev-only, read-only)
        <span v-if="data" class="badge">enabled</span>
      </summary>

      <div class="inspector-body">
        <div class="inspector-controls">
          <button @click="loadPreview" :disabled="loading" class="refresh-btn">
            {{ loading ? '⏳ Loading…' : '↻ Refresh' }}
          </button>
          <div class="tab-bar">
            <button :class="{ active: activeTab === 'full' }" @click="activeTab = 'full'">Full prompt</button>
            <button :class="{ active: activeTab === 'sections' }" @click="activeTab = 'sections'">Sections</button>
            <button :class="{ active: activeTab === 'flags' }" @click="activeTab = 'flags'">Flags</button>
          </div>
        </div>

        <div v-if="error" class="inspector-error">⚠ {{ error }}</div>

        <div v-if="data" class="inspector-content">
          <div v-if="activeTab === 'full'">
            <pre class="prompt-text">{{ data.system_prompt }}</pre>
            <p class="meta">
              <strong>Character:</strong> {{ data.character_id }}
              &nbsp;|&nbsp;
              <strong>Generated:</strong> {{ data.generated_at }}
              &nbsp;|&nbsp;
              <strong>Length:</strong> {{ data.system_prompt.length }} chars
            </p>
          </div>

          <div v-if="activeTab === 'sections'" class="sections-view">
            <div v-for="(value, key) in data.sections" :key="key" class="section-block">
              <h5>{{ key }}</h5>
              <pre class="prompt-text">{{ value || '(empty)' }}</pre>
            </div>
            <p class="note">Template placeholders: {{ data.template_constant_keys.join(', ') }}</p>
          </div>

          <div v-if="activeTab === 'flags'" class="flags-view">
            <ul>
              <li v-for="(value, key) in data.flags" :key="key">
                <code>{{ key }}</code>: <strong>{{ value }}</strong>
              </li>
            </ul>
            <p class="note">State summary: {{ JSON.stringify(data.state_summary) }}</p>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

<style scoped>
.prompt-inspector-panel {
  margin: 1rem 0;
  font-size: 0.9rem;
}
.inspector-details {
  background: rgba(20, 20, 30, 0.85);
  border: 1px solid #555;
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
}
.inspector-summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  user-select: none;
  list-style: none;
}
.inspector-summary::-webkit-details-marker {
  display: none;
}
.summary-arrow {
  color: #ffcc66;
}
.badge {
  margin-left: auto;
  font-size: 0.7rem;
  background: #2a5;
  color: #fff;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
}
.inspector-body {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.inspector-controls {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}
.refresh-btn {
  background: #2a4;
  color: #fff;
  border: 0;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  cursor: pointer;
}
.refresh-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.tab-bar {
  display: flex;
  gap: 0.25rem;
  margin-left: auto;
}
.tab-bar button {
  background: #333;
  color: #ccc;
  border: 1px solid #555;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  border-radius: 4px;
  font-size: 0.85rem;
}
.tab-bar button.active {
  background: #446;
  color: #fff;
  border-color: #88f;
}
.inspector-error {
  color: #f88;
  font-weight: bold;
}
.inspector-content {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.prompt-text {
  background: #111;
  color: #cde;
  border: 1px solid #333;
  border-radius: 4px;
  padding: 0.75rem;
  font-family: 'Menlo', 'Consolas', monospace;
  font-size: 0.78rem;
  line-height: 1.4;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 480px;
  overflow-y: auto;
}
.section-block {
  margin-bottom: 0.5rem;
}
.section-block h5 {
  margin: 0.25rem 0;
  color: #ccc;
  font-family: monospace;
  font-size: 0.85rem;
}
.meta {
  color: #888;
  font-size: 0.8rem;
}
.note {
  color: #888;
  font-size: 0.8rem;
  font-style: italic;
}
.flags-view ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.flags-view li {
  padding: 0.25rem 0;
  border-bottom: 1px dashed #444;
}
.flags-view code {
  color: #ffcc66;
}
</style>
