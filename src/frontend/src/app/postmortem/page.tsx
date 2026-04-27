'use client'

import { useCallback, useState } from 'react'
import SseStream from '@/components/SseStream'
import { streamPostmortem } from '@/lib/sse'

export default function PostmortemPage() {
  const [analysisJson, setAnalysisJson] = useState('')
  const [context, setContext] = useState('')
  const [parseError, setParseError] = useState<string | null>(null)

  const handleStream = useCallback(
    (onToken: (t: string) => void, onDone: (n: number) => void, onError: (m: string) => void, signal: AbortSignal) => {
      let parsed: object
      try {
        parsed = JSON.parse(analysisJson)
        setParseError(null)
      } catch {
        setParseError('Invalid JSON in log analysis field')
        return Promise.resolve()
      }
      return streamPostmortem(parsed, undefined, context || undefined, onToken, onDone, onError, signal)
    },
    [analysisJson, context],
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-green-400 mb-1">Postmortem Generator</h1>
        <p className="text-gray-500 text-sm">
          Paste the JSON output from the log analyzer to generate a Google SRE Workbook–style postmortem.
        </p>
      </div>

      <div className="space-y-2">
        <label className="text-xs text-gray-500 uppercase tracking-wider">Log analysis JSON</label>
        <textarea
          value={analysisJson}
          onChange={(e) => setAnalysisJson(e.target.value)}
          placeholder='{"severity":"critical","summary":"...","root_cause":"...","runbook":[...],"related_metrics":[...]}'
          rows={8}
          className="w-full p-3 bg-gray-900 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-600 font-mono resize-y focus:outline-none focus:border-green-700"
        />
        {parseError && <p className="text-red-400 text-xs">{parseError}</p>}
      </div>

      <div className="space-y-2">
        <label className="text-xs text-gray-500 uppercase tracking-wider">Additional context (optional)</label>
        <input
          type="text"
          value={context}
          onChange={(e) => setContext(e.target.value)}
          placeholder="e.g. Production HDFS cluster, 2024-06-21 incident"
          className="w-full p-3 bg-gray-900 border border-gray-700 rounded text-sm text-gray-200 placeholder-gray-600 font-mono focus:outline-none focus:border-green-700"
        />
      </div>

      <SseStream onStream={handleStream} placeholder="Postmortem will stream here..." />
    </div>
  )
}
