// @vitest-environment jsdom
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import GameInsights from './GameInsights'
import * as api from '../api'

vi.mock('../api', () => ({
  generateGameSummary: vi.fn(),
  generateReviewExplanation: vi.fn(),
  getGameSummary: vi.fn(),
  listGameEvents: vi.fn(),
}))

beforeEach(() => {
  vi.resetAllMocks()
  api.getGameSummary.mockResolvedValue({
    headline: 'Aces game summary',
    summary: 'The recorded official totals are summarized.',
    key_performers: [{ player_id: 'player-1', observation: 'Alex recorded 4 points.' }],
    data_quality_caveats: ['Official stats remain the source of truth.'],
  })
  api.listGameEvents.mockResolvedValue([
    { id: 'event-1', event_type: 'shot', start_frame: 2, confidence_score: 0.8 },
  ])
  api.generateReviewExplanation.mockResolvedValue({
    headline: 'Shot review',
    explanation: 'The source event is a shot at frame 3.',
  })
})

afterEach(cleanup)

test('loads the summary and requests an explanation for the selected event', async () => {
  const user = userEvent.setup()
  render(<GameInsights gameId="game-1" />)

  expect(await screen.findByText('Aces game summary')).toBeTruthy()
  expect(screen.getByText(/official stats are unchanged/)).toBeTruthy()
  await user.click(screen.getByRole('button', { name: 'Explain event' }))

  expect(api.generateReviewExplanation).toHaveBeenCalledWith('game-1', 'event-1')
  expect(await screen.findByText('Shot review')).toBeTruthy()
})

test('shows backend errors instead of hiding failed summary requests', async () => {
  api.getGameSummary.mockRejectedValue(new Error('Service unavailable'))
  render(<GameInsights gameId="game-1" />)

  expect((await screen.findByRole('alert')).textContent).toContain('Service unavailable')
  expect(screen.getByRole('button', { name: 'Generate summary' })).toBeTruthy()
})
