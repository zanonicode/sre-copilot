import Link from 'next/link'

export default function Home() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[70vh] gap-8 text-center">
      <div>
        <h1 className="text-4xl font-bold text-green-400 mb-2">SRE Copilot</h1>
        <p className="text-gray-400 text-lg">
          AI-powered log analysis and postmortem generation
        </p>
      </div>
      <div className="flex gap-4">
        <Link
          href="/analyzer"
          className="px-6 py-3 bg-green-600 hover:bg-green-500 text-white rounded-lg transition-colors"
        >
          Analyze Logs
        </Link>
        <Link
          href="/postmortem"
          className="px-6 py-3 border border-gray-700 hover:border-gray-500 text-gray-300 rounded-lg transition-colors"
        >
          Generate Postmortem
        </Link>
      </div>
    </div>
  )
}
