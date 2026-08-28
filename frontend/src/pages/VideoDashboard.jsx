import { useCallback, useEffect, useState } from 'react'
import { listGames } from '../api'
import UploadForm from '../components/UploadForm'
import GamesList from '../components/GamesList'
import FrameViewer from '../components/FrameViewer'
import PlayerStatsTable from '../components/PlayerStatsTable'

export default function VideoDashboard() {
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

  const videoGames = games.filter((g) => g.entry_mode !== 'manual')
  const selectedGame = videoGames.find((g) => g.id === selectedGameId)

  return (
    <div className="flex flex-col gap-6">
      <UploadForm onUploaded={refresh} />
      <GamesList games={videoGames} onRefresh={refresh} selectedGameId={selectedGameId} onSelect={setSelectedGameId} />
      {selectedGame && <FrameViewer game={selectedGame} onGameUpdated={handleGameUpdated} />}
      {selectedGame && <PlayerStatsTable gameId={selectedGame.id} refreshKey={statsRefreshKey} />}
    </div>
  )
}
