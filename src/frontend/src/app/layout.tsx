import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'SRE Copilot',
  description: 'AI-powered log analysis and postmortem generation',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-950 text-gray-100 min-h-screen font-mono antialiased">
        <nav className="border-b border-gray-800 px-6 py-3 flex items-center gap-6">
          <span className="text-green-400 font-bold tracking-tight">SRE Copilot</span>
          <a href="/analyzer" className="text-gray-400 hover:text-gray-100 text-sm transition-colors">
            Analyzer
          </a>
          <a href="/postmortem" className="text-gray-400 hover:text-gray-100 text-sm transition-colors">
            Postmortem
          </a>
        </nav>
        <main className="container mx-auto px-6 py-8 max-w-5xl">{children}</main>
      </body>
    </html>
  )
}
