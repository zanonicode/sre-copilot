'use client'

const SAMPLES: Record<string, { label: string; logs: string }> = {
  hdfs_datanode: {
    label: 'HDFS DataNode Failure',
    logs: `081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_-1608999687919862906 src: /10.251.73.220:54106 dest: /10.251.73.220:50010
081109 203519 143 INFO dfs.DataNode$PacketResponder: PacketResponder 1 for block blk_-1608999687919862906 terminating
081109 203519 35 ERROR dfs.DataNode$DataXceiver: 10.251.75.228:50010:DataXceiver: blk_-1608999687919862906 Got exception while serving blk_-1608999687919862906
java.io.IOException: Connection reset by peer
081109 203520 35 WARN dfs.DataNode: IOException in offerService
081109 203520 35 ERROR dfs.DataNode: DatanodeRegistered at namenode: 10.251.73.220:9000 error
081109 203522 35 ERROR dfs.DataNode: DataNode is shutting down: java.io.IOException: Failed to write block blk_-1608999687919862906 to mirror 10.251.73.220`,
  },
  cascade_retry: {
    label: 'Cascade Retry Storm',
    logs: `GET /upstream/api timed out after 5000ms
retrying GET /upstream/api (attempt 2/3)
retrying GET /upstream/api (attempt 3/3)
circuit breaker OPEN for upstream-api
503 Service Unavailable returned to 47 queued requests
downstream latency p99: 8230ms`,
  },
  memory_leak: {
    label: 'Memory Leak / OOM',
    logs: `GC pause 1.4s, heap=82%
GC pause 1.8s, heap=89%
GC pause 2.1s, heap=94%
heap=96%, eviction failed
OOMKiller invoked: killed process backend-worker-3 (pid 12847)
Service recovered after pod restart`,
  },
}

interface SampleButtonsProps {
  onSelect: (logs: string) => void
}

export default function SampleButtons({ onSelect }: SampleButtonsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(SAMPLES).map(([key, { label, logs }]) => (
        <button
          key={key}
          onClick={() => onSelect(logs)}
          className="px-3 py-1.5 text-xs border border-gray-700 hover:border-green-600 hover:text-green-400 text-gray-400 rounded transition-colors"
        >
          {label}
        </button>
      ))}
    </div>
  )
}
