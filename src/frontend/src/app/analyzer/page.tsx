'use client'

import { useCallback, useState } from 'react'
import SseStream from '@/components/SseStream'
import SampleButtons from '@/components/SampleButtons'
import { streamAnalysis } from '@/lib/sse'

export default function AnalyzerPage() {
  const [logs, setLogs] = useState('')
  const [context, setContext] = useState('')

  const handleStream = useCallback(
    (onToken: (t: string) => void, onDone: (n: number) => void, onError: (m: string) => void, signal: AbortSignal) =>
      streamAnalysis(logs, context || undefined, onToken, onDone, onError, signal),
    [logs, context],
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-green-400 mb-1">Log Analyzer</h1>
        <p className="text-gray-500 text-sm">Paste logs below or select a sample. Analysis streams in real time.</p>
      </div>

      <div className="space-y-2">
        <label className="text-xs text-gray-500 uppercase tracking-wider">Sample scenarios</label>
        <SampleButtons onSelect={setLogs} />
      </div>

      <div className="space-y-2">
        <label className="text-xs text-gray-500 uppercase tracking-wider">Log payload</label>
        <textarea
          value={logs}
          onChange={(e) => setLogs(e.target.value)}
          placeholder="Paste log lines here..."
          rows={10}
          className="w-full p-3 bg-gray-900 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-600 font-mono resize-y focus:outline-none focus:border-green-700"
        />
      </div>

      <div className="space-y-2">
        <label className="text-xs text-gray-500 uppercase tracking-wider">Context (optional)</label>
        <input
          type="text"
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="e.g. HDFS cluster, production, 2024-06-21"
          className="w-full p-3 bg-gray-900 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-600 font-mono focus:outline-none focus:border-green-700"
        />
      </div>

      <SseStream onStream={handleStream} placeholder="Analysis will appear here..." />
    </div>
  )
}
