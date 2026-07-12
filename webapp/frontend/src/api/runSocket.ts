/** Reconnecting WebSocket for /api/runs/{id}/events (§7.5). Close 1000 = terminal
 * (buffer drained after the final status), 4404 = not the active run; anything else
 * is transport loss → reconnect with ?since=<lastSeq> after a backoff. */
import type { RunWsMsg } from '../types/runs'

export interface RunSocketHandlers {
  onMessage: (msg: RunWsMsg) => void
  onTerminal: () => void
  onGone: () => void
}

export class RunSocket {
  private readonly runId: string
  private readonly lastSeq: () => number
  private readonly handlers: RunSocketHandlers
  private ws: WebSocket | null = null
  private stopped = false
  private retryMs = 500
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(runId: string, lastSeq: () => number, handlers: RunSocketHandlers) {
    this.runId = runId
    this.lastSeq = lastSeq
    this.handlers = handlers
  }

  connect(): void {
    if (this.stopped) return
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${proto}://${window.location.host}/api/runs/${this.runId}/events?since=${this.lastSeq()}`
    const ws = new WebSocket(url)
    this.ws = ws
    ws.onmessage = (e: MessageEvent<string>) => {
      this.retryMs = 500
      this.handlers.onMessage(JSON.parse(e.data) as RunWsMsg)
    }
    ws.onclose = (e: CloseEvent) => {
      if (this.stopped || this.ws !== ws) return
      if (e.code === 1000) this.handlers.onTerminal()
      else if (e.code === 4404) this.handlers.onGone()
      else {
        this.timer = setTimeout(() => this.connect(), this.retryMs)
        this.retryMs = Math.min(this.retryMs * 2, 5000)
      }
    }
  }

  close(): void {
    this.stopped = true
    if (this.timer !== null) clearTimeout(this.timer)
    this.ws?.close()
  }
}
