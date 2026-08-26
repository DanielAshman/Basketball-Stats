import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export const api = axios.create({ baseURL: API_URL })

export async function uploadGame({ title, datePlayed, file }) {
  const formData = new FormData()
  formData.append('title', title)
  formData.append('date_played', datePlayed)
  formData.append('video', file)

  const { data } = await api.post('/api/games', formData)
  return data
}

export async function listGames() {
  const { data } = await api.get('/api/games')
  return data.games
}
