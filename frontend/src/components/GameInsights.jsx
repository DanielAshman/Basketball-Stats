import { useEffect, useState } from 'react'
import {
  generateGameSummary,
  generateReviewExplanation,
  getGameSummary,
  listGameEvents,
} from '../api'

function getErrorMessage(error) {
  const detail = error.response?.data?.detail
  return typeof detail === 'string' ? detail : error.message || 'Could not load generated insights.'
}

function describeEvent(event) {
  const frame = event.start_frame == null ? '' : ` · Frame ${event.start_frame + 1}`
  const confidence = event.confidence_score == null
    ? ''
    : ` · ${Math.round(event.confidence_score * 100)}% confidence`
  return `${event.event_type || 'Event'}${frame}${confidence}`
}

export default function GameInsights({ gameId }) {
  const [summary, setSummary] = useState(null)
  const [summaryLoading, setSummaryLoading] = useState(true)
  const [summaryError, setSummaryError] = useState(null)
  const [events, setEvents] = useState([])
  const [eventsError, setEventsError] = useState(null)
  const [selectedEventId, setSelectedEventId] = useState('')
  const [explanation, setExplanation] = useState(null)
  const [explanationLoading, setExplanationLoading] = useState(false)
  const [explanationError, setExplanationError] = useState(null)

  useEffect(() => {
    let active = true

    getGameSummary(gameId)
      .then((result) => {
        if (active) setSummary(result)
      })
      .catch((error) => {
        if (active) setSummaryError(getErrorMessage(error))
      })
      .finally(() => {
        if (active) setSummaryLoading(false)
      })

    listGameEvents(gameId)
      .then((result) => {
        if (!active) return
        setEvents(result)
        setSelectedEventId(result[0]?.id || '')
      })
      .catch((error) => {
        if (active) setEventsError(getErrorMessage(error))
      })

    return () => {
      active = false
    }
  }, [gameId])

  async function refreshSummary() {
    setSummaryLoading(true)
    setSummaryError(null)
    try {
      setSummary(await generateGameSummary(gameId))
    } catch (error) {
      setSummaryError(getErrorMessage(error))
    } finally {
      setSummaryLoading(false)
    }
  }

  async function explainEvent() {
    setExplanationLoading(true)
    setExplanationError(null)
    setExplanation(null)
    try {
      setExplanation(await generateReviewExplanation(gameId, selectedEventId || undefined))
    } catch (error) {
      setExplanationError(getErrorMessage(error))
    } finally {
      setExplanationLoading(false)
    }
  }

  return (
    <section aria-label="AI-generated game insights" className="flex flex-col gap-4 rounded-lg border border-orange-200 p-4 dark:border-orange-900">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Game insights</h2>
          <p className="text-xs text-neutral-500">Generated from recorded game data; official stats are unchanged.</p>
        </div>
        <button
          type="button"
          onClick={refreshSummary}
          disabled={summaryLoading}
          className="rounded border border-neutral-300 px-3 py-1.5 text-sm disabled:opacity-50 dark:border-neutral-600"
        >
          {summaryLoading ? 'Generating summary…' : summary ? 'Refresh summary' : 'Generate summary'}
        </button>
      </div>

      {summaryError && <p role="alert" className="text-sm text-red-600">{summaryError}</p>}
      {summaryLoading && <p role="status" className="text-sm text-neutral-500">Loading game summary…</p>}
      {summary && (
        <div className="flex flex-col gap-2">
          <h3 className="font-semibold">{summary.headline}</h3>
          <p className="text-sm">{summary.summary}</p>
          {summary.key_performers?.length > 0 && (
            <div>
              <h4 className="text-sm font-medium">Key performers</h4>
              <ul className="list-inside list-disc text-sm text-neutral-600 dark:text-neutral-300">
                {summary.key_performers.map((performer) => (
                  <li key={performer.player_id}>{performer.observation}</li>
                ))}
              </ul>
            </div>
          )}
          {summary.data_quality_caveats?.length > 0 && (
            <ul className="list-inside list-disc text-xs text-amber-700 dark:text-amber-300">
              {summary.data_quality_caveats.map((caveat, index) => <li key={`${index}-${caveat}`}>{caveat}</li>)}
            </ul>
          )}
        </div>
      )}

      <div className="flex flex-col gap-2 border-t border-neutral-200 pt-3 dark:border-neutral-700">
        <h3 className="font-semibold">Explain an event</h3>
        {eventsError && <p role="alert" className="text-sm text-red-600">{eventsError}</p>}
        {events.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={`event-${gameId}`} className="sr-only">Event to explain</label>
            <select
              id={`event-${gameId}`}
              value={selectedEventId}
              onChange={(event) => {
                setSelectedEventId(event.target.value)
                setExplanation(null)
                setExplanationError(null)
              }}
              className="min-w-48 flex-1 rounded border border-neutral-300 px-2 py-1.5 text-sm dark:border-neutral-600 dark:bg-neutral-800"
            >
              {events.map((event) => (
                <option key={event.id} value={event.id}>{describeEvent(event)}</option>
              ))}
            </select>
            <button
              type="button"
              onClick={explainEvent}
              disabled={explanationLoading || !selectedEventId}
              className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
            >
              {explanationLoading ? 'Explaining…' : 'Explain event'}
            </button>
          </div>
        ) : (
          !eventsError && <p className="text-sm text-neutral-500">No accepted events are available to explain yet.</p>
        )}
        {explanationError && <p role="alert" className="text-sm text-red-600">{explanationError}</p>}
        {explanation && (
          <div aria-live="polite" className="rounded bg-neutral-50 p-3 dark:bg-neutral-800">
            <h4 className="text-sm font-semibold">{explanation.headline}</h4>
            <p className="mt-1 text-sm">{explanation.explanation}</p>
          </div>
        )}
      </div>
    </section>
  )
}
