import { useEffect, useState } from 'react'
import { getPlayerStats } from '../api'

const DEFAULT_EMPTY_MESSAGE =
  "No shots or rebounds are attributed to a tagged player yet. Shot/rebound attribution only " +
  "resolves to a player if you've tagged the exact person detection at that moment — tag more " +
  'frames in the viewer above, then re-run Analyze.'

export default function PlayerStatsTable({ gameId, refreshKey, emptyMessage }) {
  const [players, setPlayers] = useState([])
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    getPlayerStats(gameId)
      .then((p) => {
        setPlayers(p)
        setLoaded(true)
      })
      .catch(console.error)
  }, [gameId, refreshKey])

  if (!loaded) return null

  if (players.length === 0) {
    return (
      <div className="flex flex-col gap-1 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
        <h2 className="text-lg font-semibold">Player Stats</h2>
        <p className="text-sm text-neutral-500">{emptyMessage ?? DEFAULT_EMPTY_MESSAGE}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
      <h2 className="text-lg font-semibold">Player Stats</h2>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-neutral-200 dark:border-neutral-700">
            <th className="py-2 pr-4">Player</th>
            <th className="py-2 pr-4">Shots</th>
            <th className="py-2 pr-4">1PT</th>
            <th className="py-2 pr-4">2PT</th>
            <th className="py-2 pr-4">3PT</th>
            <th className="py-2 pr-4">Points</th>
            <th className="py-2 pr-4">Rebounds</th>
            <th className="py-2 pr-4">Turnovers</th>
            <th className="py-2 pr-4">Assists</th>
          </tr>
        </thead>
        <tbody>
          {players.map((p) => (
            <tr key={p.player_id} className="border-b border-neutral-100 dark:border-neutral-800">
              <td className="py-2 pr-4">
                {p.team === 'away' ? 'Away' : 'Home'} #{p.jersey_number}
                {p.player_name ? ` ${p.player_name}` : ''}
              </td>
              <td className="py-2 pr-4">
                {p.shots_made}/{p.shots_attempted}
              </td>
              <td className="py-2 pr-4">{p.one_pointers_made}</td>
              <td className="py-2 pr-4">{p.two_pointers_made}</td>
              <td className="py-2 pr-4">{p.three_pointers_made}</td>
              <td className="py-2 pr-4">{p.points}</td>
              <td className="py-2 pr-4">{p.rebounds}</td>
              <td className="py-2 pr-4">{p.turnovers}</td>
              <td className="py-2 pr-4">{p.assists}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
