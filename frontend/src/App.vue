<script setup lang="ts">
import { RouterView } from 'vue-router'
</script>

<template>
  <div id="app-root">
    <RouterView />
  </div>
</template>

<style>
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;700&family=Outfit:wght@300;400;500;600;700&display=swap');

/* Global styles & premium design system tokens */
:root {
  --color-bg: #07050d;
  --color-primary: #120d24;
  --color-accent: #d4af37;
  --color-accent-hover: #f1c40f;
  --color-accent-rgb: 212, 175, 55;
  --color-text: #f5f6fa;
  --color-text-muted: #a4b0be;
  --color-border: rgba(212, 175, 55, 0.18);
  
  /* Glassmorphism specs */
  --color-glass-bg: rgba(18, 13, 36, 0.65);
  --color-glass-border: rgba(255, 255, 255, 0.06);
  --color-glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.6);
  
  /* Semantic state colors */
  --color-success: #2ecc71;
  --color-warning: #f1c40f;
  --color-danger: #e74c3c;
  
  /* Fonts */
  --font-title: 'Cinzel', Georgia, serif;
  --font-body: 'Outfit', -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  
  --shadow-glow: 0 0 15px rgba(212, 175, 55, 0.25);
  --transition-smooth: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
  --border-radius-m: 12px;
  --border-radius-s: 6px;
}

* {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: var(--font-body);
  background: var(--color-bg);
  color: var(--color-text);
  line-height: 1.6;
  min-height: 100vh;
  overflow-x: hidden;
  background-image: 
    radial-gradient(at 0% 0%, rgba(30, 20, 70, 0.3) 0px, transparent 50%),
    radial-gradient(at 100% 100%, rgba(60, 20, 40, 0.2) 0px, transparent 50%);
}

#app-root {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

/* Custom Scrollbar for premium feel */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: rgba(0, 0, 0, 0.2);
}

::-webkit-scrollbar-thumb {
  background: rgba(212, 175, 55, 0.2);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(212, 175, 55, 0.4);
}

/* Titles style */
h1, h2, h3, .magic-text {
  font-family: var(--font-title);
  letter-spacing: 0.05em;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.5);
}

/* Buttons glow */
button {
  font-family: var(--font-body);
}
</style>
