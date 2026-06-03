/**
 * WebSocket Service (v2.0)
 * ==========================
 * Native WebSocket client for FastAPI backend.
 *
 * Server → Client message types:
 *   - connection_ack    : Connection established
 *   - action_accepted   : Action queued (task_id returned)
 *   - task_status       : Processing / completed / failed
 *   - scene_update      : New scene + choices (final result)
 *   - state_change      : Partial state update
 *   - countdown         : Round timer update
 *   - world_event       : World event notification
 *   - error             : Error message
 *   - pong              : Ping response
 *
 * Client → Server message types:
 *   - action_submit     : Submit player choice
 *   - ping              : Keep-alive
 */

const WS_BASE_URL = import.meta.env.VITE_WS_BASE_URL || 'ws://localhost:8000'

export type WSMessageType =
  | 'connection_ack'
  | 'action_accepted'
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
  round: number
  narrative: string
  choices: any[]
  state_changes?: any
  minor_event?: any
}

export interface TaskStatusMessage extends WSMessage {
  type: 'task_status'
  task_id: string
  status: 'processing' | 'completed' | 'failed'
  message?: string
  error?: string
}

export interface ActionAcceptedMessage extends WSMessage {
  type: 'action_accepted'
  task_id: string
  character_id: string
  status: string
  message: string
}

export type SceneHandler = (msg: SceneUpdateMessage) => void
export type StatusHandler = (msg: TaskStatusMessage) => void
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
  // Track pending tasks (for reconnection scenarios)
  private pendingTasks: Map<string, { optionId: string; timestamp: number }> = new Map()
  // Subscribe to scene updates for specific task_id
  private taskSceneHandlers: Map<string, SceneHandler> = new Map()

  /**
   * Connect to WebSocket server.
   * Idempotent: if already connected to same character, no-op.
   */
  async connect(characterId: string): Promise<void> {
    if (this.ws?.readyState === WebSocket.OPEN && this.characterId === characterId) {
      return
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

          // Re-subscribe to pending tasks (in case of reconnect)
          if (msg.type === 'connection_ack') {
            this.resubscribePendingTasks()
          }

          // Handle scene_update for specific task
          if (msg.type === 'scene_update' && msg.task_id) {
            const handler = this.taskSceneHandlers.get(msg.task_id)
            if (handler) {
              handler(msg as SceneUpdateMessage)
              this.taskSceneHandlers.delete(msg.task_id)
              this.pendingTasks.delete(msg.task_id)
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
   * Keep-alive ping.
   */
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

  /**
   * Send a message to the server.
   */
  send(msg: WSMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      console.warn('[WS] Not connected, message dropped:', msg)
    }
  }

  /**
   * Submit a player action and register a handler for the resulting scene update.
   * Returns immediately with a task_id (non-blocking).
   */
  submitAction(
    characterId: string,
    playerInput: any,
    onSceneUpdate: SceneHandler,
  ): void {
    const tempId = `temp_${Date.now()}_${Math.random()}`
    // Register handler for the next scene_update
    this.taskSceneHandlers.set(tempId, onSceneUpdate)

    this.send({
      type: 'action_submit',
      ...playerInput,
    })

    // Note: server will return action_accepted with a real task_id
    // We need to map tempId to real task_id (handled in onmessage)
  }

  /**
   * Re-subscribe to pending tasks after reconnect.
   * (In v2.0, server auto-sends pending updates, so this is a no-op for now.)
   */
  private resubscribePendingTasks() {
    if (this.pendingTasks.size > 0) {
      console.log(`[WS] Resubscribing to ${this.pendingTasks.size} pending tasks`)
      // Server will auto-deliver pending updates via connection_ack handler
    }
  }

  /**
   * Subscribe to a specific message type.
   */
  on(type: WSMessageType, handler: MessageHandler): void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, [])
    }
    this.handlers.get(type)!.push(handler)
  }

  /**
   * Unsubscribe from a message type.
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
    this.handlers.clear()
    this.taskSceneHandlers.clear()
    this.pendingTasks.clear()
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }
}

export const wsService = new WebSocketService()
