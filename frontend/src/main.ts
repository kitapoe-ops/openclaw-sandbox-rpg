import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

// Phase L2-E hotfix: install GLOBAL error handlers as the very
// FIRST thing in the bundle, BEFORE any import can throw. This
// way we never get a 'blank black screen' with no diagnostics
// — any error from this point forward is visible on the page.

function renderFatal(text: string) {
  try {
    // If body isn't ready yet, write to document directly
    const root = document.body || document.documentElement
    if (!root) {
      // Last-resort: write to document
      document.write(
        '<pre style="position:fixed;top:0;left:0;right:0;bottom:0;' +
        'background:#1a1a1a;color:#ff6b6b;padding:1rem;' +
        'font-family:monospace;font-size:12px;white-space:pre-wrap;' +
        'z-index:99999;overflow:auto;">' +
        text.replace(/[<>&]/g, (c: string) =>
          ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' } as Record<string, string>)[c] || c
        ) +
        '</pre>'
      )
      return
    }
    const pre = document.createElement('pre')
    pre.id = 'fatal-error-display'
    pre.style.cssText = (
      'position:fixed;top:0;left:0;right:0;bottom:0;' +
      'background:#1a1a1a;color:#ff6b6b;padding:1rem;' +
      'font-family:monospace;font-size:12px;white-space:pre-wrap;' +
      'z-index:99999;overflow:auto;margin:0;'
    )
    pre.textContent = text
    root.appendChild(pre)
  } catch (_e) {
    // Give up — at least we logged to console
    console.error('[fatal-error-display failed]', _e)
  }
}

// Global window.onerror — catches ANY uncaught error, even
// pre-Vue errors. The user always sees the message.
const oldOnError = window.onerror
window.onerror = function (
  msg: string | Event,
  url?: string,
  line?: number,
  col?: number,
  err?: Error,
): boolean {
  const text = (
    '[FATAL: window.onerror]\n\n' +
    String(msg) + '\n\n' +
    'at ' + (url || '?') + ':' + (line ?? '?') + ':' + (col ?? '?') + '\n\n' +
    (err && err.stack ? err.stack : '') + '\n\n' +
    'Reload to retry.'
  )
  renderFatal(text)
  console.error('[window.onerror]', text)
  if (typeof oldOnError === 'function') {
    try { oldOnError.call(window, msg, url, line, col, err) } catch (_e) { /* ignore */ }
  }
  return false
}

// Unhandled promise rejection — e.g. dynamic import() failure
window.addEventListener('unhandledrejection', (event: PromiseRejectionEvent) => {
  const reason = event.reason || '(no reason)'
  const reasonObj = reason as { stack?: string; message?: string } | null
  const text = (
    '[FATAL: unhandledrejection]\n\n' +
    (reasonObj?.stack || (reason instanceof Error ? reason.message : String(reason))) +
    '\n\nReload to retry.'
  )
  renderFatal(text)
  console.error('[unhandledrejection]', text)
})

// Synchronous try/catch around the entire Vue bootstrap
try {
  const app = createApp(App)

  app.config.errorHandler = (err: unknown, _instance: unknown, info: unknown) => {
    const errObj = err as { stack?: string; message?: string } | null
    console.error('[Vue error]', err, info)
    const text = (
      '[Vue error]\n\n' +
      (errObj?.stack || (err instanceof Error ? err.message : String(err))) + '\n\n' +
      'info: ' + String(info) + '\n\n' +
      'Reload to retry.'
    )
    renderFatal(text)
  }
  app.config.warnHandler = (msg) => {
    console.warn('[Vue warn]', msg)
  }

  app.use(createPinia())
  app.use(router)
  app.mount('#app')
  console.log('[OpenClaw] App mounted OK')
} catch (e: unknown) {
  const errObj = e as { stack?: string; message?: string } | null
  const text = (
    '[FATAL: bootstrap]\n\n' +
    (errObj?.stack || (e instanceof Error ? e.message : String(e))) + '\n\n' +
    'Reload to retry.'
  )
  renderFatal(text)
  console.error('[bootstrap error]', e)
}
