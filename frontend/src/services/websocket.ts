/**
 * WebSocket Service
 * ===================
 * 原生 WebSocket 客戶端（對應 FastAPI backend/ws/game_socket.py）
 *
 * 訊息格式：
 * Server → Client: { type: "scene_update" | "state_change" | "countdown" | "world_event", ... }
 * Client → Server: { type: "action_submit" | "ping", ... }
 */

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000'

export type WSMessageType =
  | 'scene_update'
  | 'state_change'
  | 'countdown'
  | 'world_event'
  | 'ping'
  | 'pong'
  | 'connection_ack'

export interface WSMessage {
  type: WSMessageType
  [key: string]: any
}

type MessageHandler = (msg: WSMessage) => void

class WebSocketService {
  private ws: WebSocket | null = null
  private characterId: string | null = null
  private handlers: Map<WSMessageType, MessageHandler[]> = new Map()
  private reconnectAttempts = 0
  private maxReconnectAttempts = 5
  private reconnectInterval: number | null = null
  private pingInterval: number | null = null
  private isConnecting = false

  /**
   * 連接到 WebSocket server
   */
  async connect(characterId: string): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN && this.characterId === characterId) {
      return // 已連接
    }

    if (this.isConnecting) return
    this.isConnecting = true
    this.characterId = characterId

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
   * 自動重連
   */
  private attemptReconnect() {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('[WS] Max reconnect attempts reached')
      return
    }
    if (!this.characterId) return

    this.reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 10000)
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)

    this.reconnectInterval = window.setTimeout(() => {
      if (this.characterId) {
        this.connect(this.characterId).catch(console.error)
      }
    }, delay)
  }

  /**
   * 保持連接活躍
   */
  private startPing() {
    this.pingInterval = window.setInterval(() => {
      this.send({ type: 'ping' })
    }, 30000) // 每 30 秒 ping 一次
  }

  private stopPing() {
    if (this.pingInterval) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  /**
   * 發送訊息
   */
  send(msg: WSMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      console.warn('[WS] Not connected, message dropped:', msg)
    }
  }

  /**
   * 監聽特定類型嘅訊息
   */
  on(type: WSMessageType, handler: MessageHandler): void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, [])
    }
    this.handlers.get(type)!.push(handler)
  }

  /**
   * 取消監聽
   */
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

  /**
   * 分派訊息
   */
  private dispatch(msg: WSMessage) {
    const handlers = this.handlers.get(msg.type) || []
    handlers.forEach(h => h(msg))
  }

  /**
   * 斷開連接
   */
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
    this.handlers.clear()
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

export const wsService = new WebSocketService()
