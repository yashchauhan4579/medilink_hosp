type FeedCallback = (jpeg: Blob, meta: any) => void
type AlertCallback = (alert: any) => void

export function connectFeed(cameraId: number, onFrame: FeedCallback): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/ws/feed/${cameraId}`
  let ws: WebSocket | null = null
  let closed = false
  let retryDelay = 1000

  function connect() {
    if (closed) return
    ws = new WebSocket(url)
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => { retryDelay = 1000 }

    ws.onmessage = (event) => {
      const data = new Uint8Array(event.data as ArrayBuffer)
      if (data.length < 4) return

      // Parse: 4-byte JSON len (LE) + JSON + JPEG
      const jsonLen = data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
      const jsonBytes = data.slice(4, 4 + jsonLen)
      const jpegBytes = data.slice(4 + jsonLen)

      const meta = JSON.parse(new TextDecoder().decode(jsonBytes))
      const blob = new Blob([jpegBytes], { type: 'image/jpeg' })
      onFrame(blob, meta)
    }

    ws.onclose = () => {
      if (!closed) {
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 10000)
      }
    }

    ws.onerror = () => ws?.close()
  }

  connect()

  return () => {
    closed = true
    ws?.close()
  }
}

export function connectAlerts(onAlert: AlertCallback): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const url = `${proto}://${location.host}/ws/alerts`
  let ws: WebSocket | null = null
  let closed = false
  let retryDelay = 1000

  function connect() {
    if (closed) return
    ws = new WebSocket(url)

    ws.onopen = () => { retryDelay = 1000 }

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'new_alert') {
        onAlert(data.alert)
      }
    }

    ws.onclose = () => {
      if (!closed) {
        setTimeout(connect, retryDelay)
        retryDelay = Math.min(retryDelay * 2, 10000)
      }
    }

    ws.onerror = () => ws?.close()
  }

  connect()

  return () => {
    closed = true
    ws?.close()
  }
}
