import { useEffect, useRef } from 'react'

const STATUS_STYLES = {
  pending: 'bg-neutral-200 text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200',
  processing: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  detecting: 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200',
  completed: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  failed: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
}

const ACTIVE_STATUSES = new Set(['pending', 'processing', 'detecting'])

export default function GamesList({ games, onRefresh, selectedGameId, onSelect }) {
  const hasActiveGame = games.some((g) => ACTIVE_STATUSES.has(g.processing_status))
  const intervalRef = useRef(null)

  useEffect(() => {
    if (!hasActiveGame) return undefined
    intervalRef.current = setInterval(onRefresh, 3000)
    return () => clearInterval(intervalRef.current)
  }, [hasActiveGame, onRefresh])

  if (games.length === 0) {
    return <p className="text-sm text-neutral-500">No games uploaded yet.</p>
  }

  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-lg font-semibold">Games</h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-max text-left text-sm">
          <thead>
            <tr className="border-b border-neutral-200 dark:border-neutral-700">
              <th className="py-2 pr-4">Title</th>
              <th className="py-2 pr-4">Date</th>
              <th className="py-2 pr-4">Status</th>
              <th className="py-2 pr-4">Frames</th>
              <th className="py-2 pr-4">Shots</th>
            </tr>
          </thead>
          <tbody>
            {games.map((g) => (
              <tr
                key={g.id}
                onClick={() => g.processing_status === 'completed' && onSelect?.(g.id)}
                className={`border-b border-neutral-100 dark:border-neutral-800 ${
                  g.processing_status === 'completed' ? 'cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800' : ''
                } ${selectedGameId === g.id ? 'bg-neutral-50 dark:bg-neutral-800' : ''}`}
              >
                <td className="py-2 pr-4">{g.title}</td>
                <td className="py-2 pr-4">{g.date_played}</td>
                <td className="py-2 pr-4">
                  <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[g.processing_status] ?? ''}`}>
                    {g.processing_status}
                  </span>
                  {g.processing_status === 'failed' && g.processing_error && (
                    <span className="ml-2 text-xs text-red-500" title={g.processing_error}>
                      {g.processing_error}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-4">{g.frame_count ?? '—'}</td>
                <td className="py-2 pr-4">
                  {g.total_shots ? `${g.made_shots}/${g.total_shots}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
