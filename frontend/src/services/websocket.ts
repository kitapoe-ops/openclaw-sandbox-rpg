/**
 * WebSocket Service (v3.1)
 * ==========================
 * Updated for production deployment:
 * - Default to wss:// (HTTPS) for Cloudflare Tunnel
 * - Handle state_mismatch error -> force state refresh
 * - Handle INTERRUPTED actions from server
 *
 * Recovery flow on reconnect:
 *   1. WS connects -> server sends connection_ack
 *   2. Client calls REST GET /api/scene/{id} for latest state
 *   3. Client calls REST GET /api/character/{id} for character state
 *   4. If server reports state_mismatch, client refreshes state immediately
 */

// Phase L2-H: Vite's `import.meta.env` is the right way to set per-build
// defaults. We default to the same origin as the page (works for both
// localhost dev and production tunnel). The .env.production file sets
// VITE_API_BASE_URL=https://rpg.kitahim.uk and VITE_WS_BASE_URL=wss://...
// which Vite inlines at build time.
const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000'
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export type WSMessageType =
  | 'connection_ack'
  | 'action_accepted'
  | 'action_submit'
  | 'task_status'
  | 'scene_update'
  | 'state_change'
  | 'countdown'
  | 'world_event'
  | 'error'
  | 'ping'
  | 'pong'

export interface WSMessage {
  type: WSMessageType
  [key: string]: any
}

export interface SceneUpdateMessage extends WSMessage {
  type: 'scene_update'
  task_id: string
  action_id: string
  round: number
  scene_id: string
  narrative: string
  choices: any[]
  state_changes?: any
  minor_event?: any
  timestamp?: string
}

export interface ActionAcceptedMessage extends WSMessage {
  type: 'action_accepted'
  task_id: string
  action_id: string
  character_id: string
  scene_id: string
  status: string
  message: string
}

export interface TaskStatusMessage extends WSMessage {
  type: 'task_status'
  task_id: string
  action_id?: string
  status: 'processing' | 'completed' | 'failed' | 'interrupted'
  message?: string
  error?: string
}

export interface StateMismatchMessage extends WSMessage {
  type: 'error'
  code: 'state_mismatch'
  client_scene_id: string
  server_scene_id: string
}

export type MessageHandler = (msg: WSMessage) => void

class WebSocketService {
  private ws: WebSocket | null = null
  private characterId: string | null = null
  private handlers: Map<WSMessageType, MessageHandler[]> = new Map()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectInterval: number | null = null
  private pingInterval: number | null = null
  private isConnecting = false
  private onReconnectHandler: (() => void | Promise<void>) | null = null
  private onStateMismatchHandler: ((clientId: string, serverId: string) => void) | null = null

  /**
   * Connect to WebSocket server.
   * Idempotent: if already connected to same character, no-op.
   */
  async connect(
    characterId: string,
    onReconnect?: () => void | Promise<void>,
    onStateMismatch?: (clientId: string, serverId: string) => void,
  ): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN && this.characterId === characterId) {
      return
    }
    if (this.isConnecting) return
    this.isConnecting = true
    this.characterId = characterId
    if (onReconnect) this.onReconnectHandler = onReconnect
    if (onStateMismatch) this.onStateMismatchHandler = onStateMismatch

    return new Promise((resolve, reject) => {
      const url = `${WS_BASE_URL}/ws/game/${characterId}`
      this.ws = new WebSocket(url)

      this.ws.onopen = () => {
        console.log(`[WS] Connected to ${url}`)
        this.reconnectAttempts = 0
        this.isConnecting = false
        this.startPing()
        resolve()
      }

      this.ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data)
          this.dispatch(msg)

          // Handle state_mismatch -> force refresh
          if (msg.type === 'error' && msg.code === 'state_mismatch') {
            console.warn('[WS] State mismatch detected, forcing refresh')
            if (this.onStateMismatchHandler) {
              this.onStateMismatchHandler(msg.client_scene_id, msg.server_scene_id)
            }
          }
        } catch (e) {
          console.error('[WS] Failed to parse message:', e)
        }
      }

      this.ws.onerror = (error) => {
        console.error('[WS] Error:', error)
        this.isConnecting = false
        reject(error)
      }

      this.ws.onclose = () => {
        console.log('[WS] Disconnected')
        this.stopPing()
        this.attemptReconnect()
      }
    })
  }

  /**
   * Auto-reconnect with exponential backoff.
   */
  private async attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS] Max reconnect attempts reached')
      return
    }
    if (!this.characterId) return

    this.reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000)
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)

    this.reconnectInterval = window.setTimeout(async () => {
      if (!this.characterId) return
      try {
        await this.connect(
          this.characterId,
          this.onReconnectHandler || undefined,
          this.onStateMismatchHandler || undefined,
        )
        if (this.onReconnectHandler) {
          console.log('[WS] Reconnected, refreshing state from REST...')
          await this.onReconnectHandler()
        }
      } catch (e) {
        console.error('[WS] Reconnect failed:', e)
      }
    }, delay)
  }

  private startPing() {
    this.pingInterval = window.setInterval(() => {
      this.send({ type: 'ping' })
    }, 30000)
  }

  private stopPing() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  send(msg: WSMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      console.warn('[WS] Not connected, message dropped:', msg)
    }
  }

  on(type: WSMessageType, handler: MessageHandler): void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, [])
    }
    this.handlers.get(type)!.push(handler)
  }

  off(type: WSMessageType, handler?: MessageHandler): void {
    if (!this.handlers.has(type)) return
    const list = this.handlers.get(type)!
    if (handler) {
      const idx = list.indexOf(handler)
      if (idx > -1) list.splice(idx, 1)
    } else {
      this.handlers.set(type, [])
    }
  }

  private dispatch(msg: WSMessage) {
    const handlers = this.handlers.get(msg.type) || []
    handlers.forEach(h => h(msg))
  }

  disconnect(): void {
    if (this.reconnectInterval) {
      clearTimeout(this.reconnectInterval)
      this.reconnectInterval = null
    }
    this.stopPing()
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.characterId = null
    this.onReconnectHandler = null
    this.onStateMismatchHandler = null
    this.handlers.clear()
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

export const wsService = new WebSocketService()
export { API_BASE_URL }
