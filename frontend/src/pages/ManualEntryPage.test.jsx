// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ManualEntryPage from './ManualEntryPage'
import * as api from '../api'

vi.mock('../api', () => ({
  listGamePlayers: vi.fn(), listGames: vi.fn(), listManualEvents: vi.fn(), getPlayerStats: vi.fn(),
  createManualGame: vi.fn(), createOrFindPlayer: vi.fn(),
  recordManualEvent: vi.fn(), deleteManualEvent: vi.fn(),
}))

const game = { id: 'game-1', title: 'Practice', date_played: '2026-09-18', entry_mode: 'manual', made_shots: 1, total_shots: 1, total_rebounds: 0 }
const event = { id: 'event-1', player_id: 'player-23', jersey_number: 23, player_name: 'Alex', event_type: 'shot', made: true, created_at: '2026-09-18T10:00:00' }

beforeEach(() => {
  vi.resetAllMocks()
  api.listGames.mockResolvedValue([game])
  api.listManualEvents.mockResolvedValue([event])
  api.listGamePlayers.mockResolvedValue([{id: 'player-23', jersey_number: 23, player_name: 'Alex', team: 'home'}])
  api.getPlayerStats.mockResolvedValue([])
  api.recordManualEvent.mockResolvedValue({})
})
afterEach(cleanup)

test('resuming a game preserves the player identity when recording another stat', async () => {
  const user = userEvent.setup()
  render(<ManualEntryPage />)
  await user.click(await screen.findByRole('button', { name: /Practice/ }))
  await user.click(await screen.findByRole('button', { name: 'Rebound' }))
  await waitFor(() => expect(api.recordManualEvent).toHaveBeenCalledWith('game-1', 'player-23', 'rebound', undefined, undefined))
})

test('a failed stat save displays an error and lets the coach retry', async () => {
  api.recordManualEvent.mockRejectedValueOnce(new Error('Connection lost'))
  const user = userEvent.setup()
  render(<ManualEntryPage />)
  await user.click(await screen.findByRole('button', { name: /Practice/ }))
  await user.click(await screen.findByRole('button', { name: 'Rebound' }))
  expect((await screen.findByRole('alert')).textContent).toContain('Connection lost')
  await user.click(screen.getByRole('button', { name: 'Rebound' }))
  await waitFor(() => expect(api.recordManualEvent).toHaveBeenCalledTimes(2))
})

test('both teams can record stats for the same jersey number, including players without previous events', async () => {
  api.listManualEvents.mockResolvedValue([])
  api.listGamePlayers.mockResolvedValue([
    { id: 'home-23', jersey_number: 23, player_name: 'Alex', team: 'home' },
    { id: 'away-23', jersey_number: 23, player_name: 'Sam', team: 'away' },
  ])
  const user = userEvent.setup()
  render(<ManualEntryPage />)
  await user.click(await screen.findByRole('button', { name: /Practice/ }))
  const home = (await screen.findByText('Home #23 Alex')).parentElement
  const away = screen.getByText('Away #23 Sam').parentElement
  await user.click(within(home).getByRole('button', { name: '2 Pointer' }))
  await user.click(within(away).getByRole('button', { name: 'Assist' }))
  expect(api.recordManualEvent).toHaveBeenCalledWith('game-1', 'home-23', 'shot', true, 2)
  expect(api.recordManualEvent).toHaveBeenCalledWith('game-1', 'away-23', 'assist', undefined, undefined)
})

test('point buttons send their corresponding values', async () => {
  const user = userEvent.setup()
  render(<ManualEntryPage />)
  await user.click(await screen.findByRole('button', { name: /Practice/ }))
  const player = (await screen.findByText('Home #23 Alex')).parentElement
  await user.click(within(player).getByRole('button', { name: '1 Pointer' }))
  await user.click(within(player).getByRole('button', { name: '3 Pointer' }))
  expect(api.recordManualEvent).toHaveBeenCalledWith('game-1', 'player-23', 'shot', true, 1)
  expect(api.recordManualEvent).toHaveBeenCalledWith('game-1', 'player-23', 'shot', true, 3)
})

test('a player save completing after switching games does not enter the new roster', async () => {
  api.listGames.mockResolvedValue([game, { ...game, id: 'game-2', title: 'Second game' }])
  api.listGamePlayers.mockResolvedValue([])
  api.listManualEvents.mockResolvedValue([])
  let finishSave
  api.createOrFindPlayer.mockImplementation(() => new Promise((resolve) => { finishSave = resolve }))
  const user = userEvent.setup()
  render(<ManualEntryPage />)
  await user.click(await screen.findByRole('button', { name: /Practice/ }))
  await user.type(screen.getByLabelText('Jersey #'), '9')
  await user.click(screen.getByRole('button', { name: 'Add to roster' }))
  await user.click(screen.getByRole('button', { name: 'Switch game' }))
  await user.click(await screen.findByRole('button', { name: /Second game/ }))
  finishSave({ id: 'old-game-player', jersey_number: 9, player_name: 'Old game', team: 'home' })
  await waitFor(() => expect(screen.queryByText('Home #9 Old game')).toBeNull())
  // Allow the async save callback to settle before the final assertion.
  await user.click(screen.getByLabelText('Jersey #'))
  expect(screen.queryByText('Home #9 Old game')).toBeNull()
})
