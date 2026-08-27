import axios from 'axios'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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

export async function getFrameDetections(gameId, frameNumber) {
  const { data } = await api.get(`/api/games/${gameId}/frames/${frameNumber}/detections`)
  return data
}

export async function setHoopPosition(gameId, x, y) {
  const { data } = await api.post(`/api/games/${gameId}/hoop`, { x, y })
  return data
}

export async function analyzeGame(gameId) {
  const { data } = await api.post(`/api/games/${gameId}/analyze`)
  return data
}

export async function assignPlayer(detectionId, jerseyNumber, playerName) {
  const { data } = await api.post(`/api/detections/${detectionId}/player`, {
    jersey_number: jerseyNumber,
    player_name: playerName || null,
  })
  return data
}
