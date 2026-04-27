const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export interface SseEvent {
  type: 'delta' | 'done' | 'error'
  token?: string
  output_tokens?: number
  code?: string
  message?: string
}

export async function streamAnalysis(
  logPayload: string,
  context: string | undefined,
  onToken: (token: string) => void,
  onDone: (outputTokens: number) => void,
  onError: (msg: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/analyze/logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ log_payload: logPayload, context }),
    signal,
  })

  if (!res.ok || !res.body) {
    onError(`HTTP ${res.status}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data: ')) continue
      const evt: SseEvent = JSON.parse(line.slice(6))
      if (evt.type === 'delta' && evt.token) onToken(evt.token)
      else if (evt.type === 'done') onDone(evt.output_tokens ?? 0)
      else if (evt.type === 'error') onError(evt.message ?? 'unknown error')
    }
  }
}

export async function streamPostmortem(
  logAnalysis: object,
  timeline: object[] | undefined,
  context: string | undefined,
  onToken: (token: string) => void,
  onDone: (outputTokens: number) => void,
  onError: (msg: string) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/generate/postmortem`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({ log_analysis: logAnalysis, timeline, context }),
    signal,
  })

  if (!res.ok || !res.body) {
    onError(`HTTP ${res.status}`)
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop() ?? ''
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith('data: ')) continue
      const evt: SseEvent = JSON.parse(line.slice(6))
      if (evt.type === 'delta' && evt.token) onToken(evt.token)
      else if (evt.type === 'done') onDone(evt.output_tokens ?? 0)
      else if (evt.type === 'error') onError(evt.message ?? 'unknown error')
    }
  }
}
