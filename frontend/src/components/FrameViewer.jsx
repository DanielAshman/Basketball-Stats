import { useEffect, useRef, useState } from 'react'
import { API_URL, analyzeGame, getFrameDetections, setHoopPosition } from '../api'

const BOX_COLORS = {
  person: 'border-sky-400',
  sports_ball: 'border-orange-500',
}

export default function FrameViewer({ game, onGameUpdated }) {
  const { id: gameId, frame_count: frameCount, hoop_x, hoop_y } = game
  const [index, setIndex] = useState(0)
  const [detections, setDetections] = useState([])
  const [frameSize, setFrameSize] = useState(null)
  const [markingHoop, setMarkingHoop] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState(null)
  const imgRef = useRef(null)

  useEffect(() => {
    setIndex(0)
  }, [gameId])

  useEffect(() => {
    if (!frameCount) return
    getFrameDetections(gameId, index)
      .then((d) => {
        setDetections(d.detections)
        setFrameSize({ width: d.width, height: d.height })
      })
      .catch(console.error)
  }, [gameId, index, frameCount])

  async function handleImageClick(e) {
    if (!markingHoop || !imgRef.current || !frameSize) return
    const rect = imgRef.current.getBoundingClientRect()
    const relX = (e.clientX - rect.left) / rect.width
    const relY = (e.clientY - rect.top) / rect.height
    const x = Math.round(relX * frameSize.width)
    const y = Math.round(relY * frameSize.height)

    await setHoopPosition(gameId, x, y)
    setMarkingHoop(false)
    onGameUpdated?.()
  }

  async function handleAnalyze() {
    setAnalyzing(true)
    setAnalyzeError(null)
    try {
      await analyzeGame(gameId)
      onGameUpdated?.()
    } catch (err) {
      setAnalyzeError(err.response?.data?.detail ?? err.message)
    } finally {
      setAnalyzing(false)
    }
  }

  if (!frameCount) return null

  const hoopMarked = hoop_x != null && hoop_y != null

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Detections</h2>
        <button
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0}
          className="rounded border border-neutral-300 px-2 py-1 text-sm disabled:opacity-40 dark:border-neutral-600"
        >
          ← Prev
        </button>
        <span className="text-sm text-neutral-500">
          Frame {index + 1} / {frameCount}
        </span>
        <button
          onClick={() => setIndex((i) => Math.min(frameCount - 1, i + 1))}
          disabled={index === frameCount - 1}
          className="rounded border border-neutral-300 px-2 py-1 text-sm disabled:opacity-40 dark:border-neutral-600"
        >
          Next →
        </button>

        <span className="mx-2 h-4 w-px bg-neutral-300 dark:bg-neutral-600" />

        <button
          onClick={() => setMarkingHoop((m) => !m)}
          className={`rounded border px-2 py-1 text-sm ${
            markingHoop
              ? 'border-orange-500 bg-orange-50 text-orange-700 dark:bg-orange-950'
              : 'border-neutral-300 dark:border-neutral-600'
          }`}
        >
          {markingHoop ? 'Click the frame to set hoop…' : hoopMarked ? 'Re-mark hoop' : 'Mark hoop'}
        </button>

        <button
          onClick={handleAnalyze}
          disabled={!hoopMarked || analyzing}
          className="rounded bg-orange-600 px-3 py-1 text-sm font-medium text-white disabled:opacity-40"
        >
          {analyzing ? 'Analyzing…' : 'Analyze shots'}
        </button>
      </div>

      {!hoopMarked && (
        <p className="text-sm text-neutral-500">
          Mark the hoop's position on any frame before analyzing shots — YOLOv8's stock weights
          can't detect a hoop on their own.
        </p>
      )}
      {analyzeError && <p className="text-sm text-red-600">{analyzeError}</p>}

      <div className="relative inline-block">
        <img
          ref={imgRef}
          src={`${API_URL}/api/games/${gameId}/frames/${index}/image`}
          alt={`Frame ${index}`}
          onClick={handleImageClick}
          className={`max-w-full rounded border border-neutral-300 dark:border-neutral-600 ${markingHoop ? 'cursor-crosshair' : ''}`}
        />
        {frameSize &&
          detections.map((d, i) => (
            <div
              key={i}
              className={`absolute border-2 ${BOX_COLORS[d.object_type] ?? 'border-white'}`}
              style={{
                left: `${(d.bbox_x / frameSize.width) * 100}%`,
                top: `${(d.bbox_y / frameSize.height) * 100}%`,
                width: `${(d.bbox_width / frameSize.width) * 100}%`,
                height: `${(d.bbox_height / frameSize.height) * 100}%`,
              }}
            >
              <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-black/70 px-1 text-xs text-white">
                {d.object_type} {Math.round(d.confidence_score * 100)}%
                {d.estimated_jersey_number != null && ` · #${d.estimated_jersey_number}`}
              </span>
            </div>
          ))}
        {frameSize && hoopMarked && (
          <div
            className="absolute h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-red-500"
            style={{
              left: `${(hoop_x / frameSize.width) * 100}%`,
              top: `${(hoop_y / frameSize.height) * 100}%`,
            }}
            title="Hoop"
          />
        )}
      </div>

      {frameSize && detections.length === 0 && (
        <p className="text-sm text-neutral-500">No people or ball detected in this frame.</p>
      )}
    </div>
  )
}
