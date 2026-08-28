import { useCallback, useEffect, useState } from 'react'
import {
  createManualGame,
  createOrFindPlayer,
  deleteManualEvent,
  listGames,
  listManualEvents,
  recordManualEvent,
} from '../api'
import PlayerStatsTable from '../components/PlayerStatsTable'

const EVENT_BUTTONS = [
  { label: 'Made Shot', eventType: 'shot', made: true, color: 'bg-green-600' },
  { label: 'Missed Shot', eventType: 'shot', made: false, color: 'bg-red-600' },
  { label: 'Rebound', eventType: 'rebound', color: 'bg-sky-600' },
  { label: 'Turnover', eventType: 'turnover', color: 'bg-amber-600' },
  { label: 'Assist', eventType: 'assist', color: 'bg-purple-600' },
]

function NewGameForm({ onCreated }) {
  const [title, setTitle] = useState('')
  const [datePlayed, setDatePlayed] = useState('')
  const [creating, setCreating] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setCreating(true)
    try {
      const game = await createManualGame({ title, datePlayed })
      onCreated(game)
    } finally {
      setCreating(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
      <h2 className="text-lg font-semibold">Start a live game</h2>
      <label className="flex flex-col gap-1 text-sm">
        Title
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="vs. Eastside Warriors"
          className="rounded border border-neutral-300 px-3 py-2 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Date
        <input
          required
          type="date"
          value={datePlayed}
          onChange={(e) => setDatePlayed(e.target.value)}
          className="rounded border border-neutral-300 px-3 py-2 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>
      <button
        type="submit"
        disabled={creating}
        className="rounded bg-orange-600 px-4 py-2 font-medium text-white disabled:opacity-50"
      >
        {creating ? 'Starting…' : 'Start game'}
      </button>
    </form>
  )
}

function AddPlayerForm({ onAdd }) {
  const [jersey, setJersey] = useState('')
  const [name, setName] = useState('')

  async function handleSubmit(e) {
    e.preventDefault()
    if (jersey === '') return
    const player = await createOrFindPlayer(Number(jersey), name.trim())
    onAdd(player)
    setJersey('')
    setName('')
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2">
      <label className="flex flex-col gap-1 text-sm">
        Jersey #
        <input
          type="number"
          min="0"
          max="99"
          required
          value={jersey}
          onChange={(e) => setJersey(e.target.value)}
          className="w-20 rounded border border-neutral-300 px-2 py-1 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        Name (optional)
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-36 rounded border border-neutral-300 px-2 py-1 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>
      <button type="submit" className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-600">
        Add to roster
      </button>
    </form>
  )
}

function PlayerRow({ player, onTap }) {
  const [pending, setPending] = useState(null)

  async function handleTap(button) {
    setPending(button.label)
    try {
      await onTap(player, button)
    } finally {
      setPending(null)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded border border-neutral-200 p-2 dark:border-neutral-700">
      <span className="w-28 shrink-0 font-medium">
        #{player.jersey_number}
        {player.player_name ? ` ${player.player_name}` : ''}
      </span>
      {EVENT_BUTTONS.map((b) => (
        <button
          key={b.label}
          onClick={() => handleTap(b)}
          disabled={pending !== null}
          className={`rounded px-2 py-1 text-xs font-medium text-white disabled:opacity-50 ${b.color}`}
        >
          {pending === b.label ? '…' : b.label}
        </button>
      ))}
    </div>
  )
}

function ActivityLog({ events, onUndo }) {
  if (events.length === 0) return <p className="text-sm text-neutral-500">No events logged yet.</p>

  return (
    <ul className="flex flex-col gap-1 text-sm">
      {events.slice(0, 15).map((e) => (
        <li key={e.id} className="flex items-center justify-between gap-2 rounded px-2 py-1 odd:bg-neutral-50 dark:odd:bg-neutral-800/50">
          <span>
            #{e.jersey_number}
            {e.player_name ? ` ${e.player_name}` : ''} —{' '}
            {e.event_type === 'shot' ? (e.made ? 'Made Shot' : 'Missed Shot') : e.event_type}
          </span>
          <button onClick={() => onUndo(e.id)} className="text-xs text-neutral-500 underline hover:text-neutral-800 dark:hover:text-neutral-200">
            Undo
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function ManualEntryPage() {
  const [manualGames, setManualGames] = useState([])
  const [activeGame, setActiveGame] = useState(null)
  const [roster, setRoster] = useState([])
  const [events, setEvents] = useState([])
  const [statsRefreshKey, setStatsRefreshKey] = useState(0)

  const refreshGamesList = useCallback(() => {
    listGames()
      .then((games) => setManualGames(games.filter((g) => g.entry_mode === 'manual')))
      .catch(console.error)
  }, [])

  useEffect(() => {
    refreshGamesList()
  }, [refreshGamesList])

  const refreshEvents = useCallback(async (gameId) => {
    const evts = await listManualEvents(gameId)
    setEvents(evts)
    // Rebuild the roster to include anyone with logged events, even after a
    // page reload where the in-memory roster would otherwise be empty.
    setRoster((prev) => {
      const known = new Map(prev.map((p) => [p.jersey_number, p]))
      for (const e of evts) {
        if (!known.has(e.jersey_number)) {
          known.set(e.jersey_number, { jersey_number: e.jersey_number, player_name: e.player_name })
        }
      }
      return [...known.values()].sort((a, b) => a.jersey_number - b.jersey_number)
    })
  }, [])

  function selectGame(game) {
    setActiveGame(game)
    setRoster([])
    refreshEvents(game.id)
  }

  function handleGameCreated(game) {
    refreshGamesList()
    selectGame(game)
  }

  function handleAddPlayer(player) {
    setRoster((prev) => (prev.some((p) => p.jersey_number === player.jersey_number) ? prev : [...prev, player].sort((a, b) => a.jersey_number - b.jersey_number)))
  }

  async function handleTap(player, button) {
    await recordManualEvent(activeGame.id, player.id, button.eventType, button.made)
    await refreshEvents(activeGame.id)
    setStatsRefreshKey((k) => k + 1)
  }

  async function handleUndo(eventId) {
    await deleteManualEvent(activeGame.id, eventId)
    await refreshEvents(activeGame.id)
    setStatsRefreshKey((k) => k + 1)
  }

  if (!activeGame) {
    return (
      <div className="flex flex-col gap-6">
        <NewGameForm onCreated={handleGameCreated} />
        {manualGames.length > 0 && (
          <div className="flex flex-col gap-2">
            <h2 className="text-lg font-semibold">Resume a game</h2>
            <div className="flex flex-col gap-1">
              {manualGames.map((g) => (
                <button
                  key={g.id}
                  onClick={() => selectGame(g)}
                  className="rounded border border-neutral-200 px-3 py-2 text-left text-sm hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
                >
                  {g.title} — {g.date_played} ({g.made_shots}/{g.total_shots} shots, {g.total_rebounds} reb)
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">
          {activeGame.title} <span className="font-normal text-neutral-500">({activeGame.date_played})</span>
        </h2>
        <button
          onClick={() => setActiveGame(null)}
          className="rounded border border-neutral-300 px-3 py-1 text-sm dark:border-neutral-600"
        >
          Switch game
        </button>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
        <h3 className="font-semibold">Roster</h3>
        <AddPlayerForm onAdd={handleAddPlayer} />
        {roster.length === 0 ? (
          <p className="text-sm text-neutral-500">Add players above to start recording stats.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {roster.map((p) => (
              <PlayerRow key={p.jersey_number} player={p} onTap={handleTap} />
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
        <h3 className="font-semibold">Recent activity</h3>
        <ActivityLog events={events} onUndo={handleUndo} />
      </div>

      <PlayerStatsTable
        gameId={activeGame.id}
        refreshKey={statsRefreshKey}
        emptyMessage="No stats logged yet — tap an event button next to a player above to record one."
      />
    </div>
  )
}
