import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)

// Phase L2-E hotfix: surface any uncaught Vue errors to the page
// (otherwise we get a 'blank black screen' with no diagnostic
// info at all). Render the error into <body> so the user can at
// least see what went wrong and reload.
app.config.errorHandler = (err, _instance, info) => {
  console.error('[Vue error]', err, info)
  const body = document.body
  if (body) {
    const pre = document.createElement('pre')
    pre.style.cssText = (
      'position:fixed;top:0;left:0;right:0;bottom:0;' +
      'background:#1a1a1a;color:#ff6b6b;padding:1rem;' +
      'font-family:monospace;font-size:12px;white-space:pre-wrap;' +
      'z-index:99999;overflow:auto;'
    )
    pre.textContent =
      '[Vue error]\n\n' +
      String(err) + '\n\n' +
      'info: ' + info + '\n\n' +
      'Reload to retry.'
    body.appendChild(pre)
  }
}
app.config.warnHandler = (msg) => {
  console.warn('[Vue warn]', msg)
}

app.use(createPinia())
app.use(router)
app.mount('#app')
