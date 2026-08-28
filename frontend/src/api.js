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

export async function getPlayerStats(gameId) {
  const { data } = await api.get(`/api/games/${gameId}/players/stats`)
  return data.players
}

export async function createManualGame({ title, datePlayed, homeTeam, awayTeam }) {
  const { data } = await api.post('/api/games/manual', {
    title,
    date_played: datePlayed,
    home_team: homeTeam || null,
    away_team: awayTeam || null,
  })
  return data
}

export async function createOrFindPlayer(jerseyNumber, playerName) {
  const { data } = await api.post('/api/players', {
    jersey_number: jerseyNumber,
    player_name: playerName || null,
  })
  return data
}

export async function recordManualEvent(gameId, playerId, eventType, made) {
  const { data } = await api.post(`/api/games/${gameId}/manual-events`, {
    player_id: playerId,
    event_type: eventType,
    made: made ?? null,
  })
  return data
}

export async function listManualEvents(gameId) {
  const { data } = await api.get(`/api/games/${gameId}/manual-events`)
  return data.events
}

export async function deleteManualEvent(gameId, eventId) {
  const { data } = await api.delete(`/api/games/${gameId}/manual-events/${eventId}`)
  return data
}
