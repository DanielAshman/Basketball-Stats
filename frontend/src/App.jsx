import { useCallback, useEffect, useState } from 'react'
import { listGames } from './api'
import UploadForm from './components/UploadForm'
import GamesList from './components/GamesList'
import './App.css'

function App() {
  const [games, setGames] = useState([])

  const refresh = useCallback(() => {
    listGames().then(setGames).catch(console.error)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      <h1 className="text-2xl font-bold">Basketball Analytics</h1>
      <UploadForm onUploaded={refresh} />
      <GamesList games={games} onRefresh={refresh} />
    </div>
  )
}

export default App
