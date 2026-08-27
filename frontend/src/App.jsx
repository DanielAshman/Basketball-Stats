import { useCallback, useEffect, useState } from 'react'
import { listGames } from './api'
import UploadForm from './components/UploadForm'
import GamesList from './components/GamesList'
import FrameViewer from './components/FrameViewer'
import PlayerStatsTable from './components/PlayerStatsTable'
import './App.css'

function App() {
  const [games, setGames] = useState([])
  const [selectedGameId, setSelectedGameId] = useState(null)
  const [statsRefreshKey, setStatsRefreshKey] = useState(0)

  const refresh = useCallback(() => {
    listGames().then(setGames).catch(console.error)
  }, [])

  const handleGameUpdated = useCallback(() => {
    refresh()
    setStatsRefreshKey((k) => k + 1)
  }, [refresh])

  useEffect(() => {
    refresh()
  }, [refresh])

  const selectedGame = games.find((g) => g.id === selectedGameId)

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <h1 className="text-2xl font-bold">Basketball Analytics</h1>
      <UploadForm onUploaded={refresh} />
      <GamesList games={games} onRefresh={refresh} selectedGameId={selectedGameId} onSelect={setSelectedGameId} />
      {selectedGame && <FrameViewer game={selectedGame} onGameUpdated={handleGameUpdated} />}
      {selectedGame && <PlayerStatsTable gameId={selectedGame.id} refreshKey={statsRefreshKey} />}
    </div>
  )
}

export default App
