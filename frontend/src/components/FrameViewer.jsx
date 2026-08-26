import { useEffect, useState } from 'react'
import { API_URL, getFrameDetections } from '../api'

const BOX_COLORS = {
  person: 'border-sky-400',
  sports_ball: 'border-orange-500',
}

export default function FrameViewer({ gameId, frameCount }) {
  const [index, setIndex] = useState(0)
  const [detections, setDetections] = useState([])
  const [frameSize, setFrameSize] = useState(null)

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

  if (!frameCount) return null

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
      <div className="flex items-center gap-3">
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
      </div>

      <div className="relative inline-block">
        <img
          src={`${API_URL}/api/games/${gameId}/frames/${index}/image`}
          alt={`Frame ${index}`}
          className="max-w-full rounded border border-neutral-300 dark:border-neutral-600"
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
              </span>
            </div>
          ))}
      </div>

      {frameSize && detections.length === 0 && (
        <p className="text-sm text-neutral-500">No people or ball detected in this frame.</p>
      )}
    </div>
  )
}
