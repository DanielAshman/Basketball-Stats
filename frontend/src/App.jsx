import { useCallback, useEffect, useState } from 'react'
import { listGames } from './api'
import UploadForm from './components/UploadForm'
import GamesList from './components/GamesList'
import FrameViewer from './components/FrameViewer'
import './App.css'

function App() {
  const [games, setGames] = useState([])
  const [selectedGameId, setSelectedGameId] = useState(null)

  const refresh = useCallback(() => {
    listGames().then(setGames).catch(console.error)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const selectedGame = games.find((g) => g.id === selectedGameId)

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <h1 className="text-2xl font-bold">Basketball Analytics</h1>
      <UploadForm onUploaded={refresh} />
      <GamesList games={games} onRefresh={refresh} selectedGameId={selectedGameId} onSelect={setSelectedGameId} />
      {selectedGame && <FrameViewer game={selectedGame} onGameUpdated={refresh} />}
    </div>
  )
}

export default App
