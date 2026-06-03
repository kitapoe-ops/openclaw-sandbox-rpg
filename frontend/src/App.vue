<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div id="app-root">
    <RouterView />
  </div>
</template>

<style>
/* Global styles */
:root {
  --color-primary: #2c3e50;
  --color-accent: #b78d4a;
  --color-bg: #1a1a1a;
  --color-text: #e0e0e0;
  --color-border: #444;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft JhengHei", "PingFang TC", sans-serif;
  background: var(--color-bg);
  color: var(--color-text);
  line-height: 1.6;
}

#app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
</style>
