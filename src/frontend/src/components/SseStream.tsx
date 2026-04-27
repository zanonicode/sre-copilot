'use client'

import { useCallback, useRef, useState } from 'react'

interface SseStreamProps {
  onStream: (
    onToken: (t: string) => void,
    onDone: (n: number) => void,
    onError: (m: string) => void,
    signal: AbortSignal,
  ) => Promise<void>
  placeholder?: string
}

export default function SseStream({ onStream, placeholder }: SseStreamProps) {
  const [output, setOutput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [tokenCount, setTokenCount] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const start = useCallback(async () => {
    if (streaming) {
      abortRef.current?.abort()
      setStreaming(false)
      return
    }
    setOutput('')
    setError(null)
    setTokenCount(null)
    setStreaming(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl

    await onStream(
      (token) => setOutput((prev) => prev + token),
      (n) => { setTokenCount(n); setStreaming(false) },
      (msg) => { setError(msg); setStreaming(false) },
      ctrl.signal,
    )
  }, [streaming, onStream])

  const formatted = (() => {
    try { return JSON.stringify(JSON.parse(output), null, 2) } catch { return output }
  })()

  return (
    <div className="space-y-3">
      <button
        onClick={start}
        className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
          streaming
            ? 'bg-red-700 hover:bg-red-600 text-white'
            : 'bg-green-700 hover:bg-green-600 text-white'
        }`}
      >
        {streaming ? 'Stop' : 'Analyze'}
      </button>

      {error && (
        <div className="p-3 bg-red-950 border border-red-700 rounded text-red-300 text-sm">
          {error}
        </div>
      )}

      {(output || streaming) && (
        <div className="relative">
          <pre className="p-4 bg-gray-900 border border-gray-700 rounded text-sm text-green-300 overflow-auto max-h-96 whitespace-pre-wrap">
            {formatted || (placeholder ?? 'Streaming...')}
            {streaming && <span className="animate-pulse">|</span>}
          </pre>
          {tokenCount !== null && (
            <span className="absolute bottom-2 right-3 text-xs text-gray-600">
              {tokenCount} tokens
            </span>
          )}
        </div>
      )}
    </div>
  )
}
