import { useState } from 'react'
import { uploadGame } from '../api'

export default function UploadForm({ onUploaded }) {
  const [title, setTitle] = useState('')
  const [datePlayed, setDatePlayed] = useState('')
  const [file, setFile] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!file) {
      setError('Choose a video file first')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await uploadGame({ title, datePlayed, file })
      setTitle('')
      setDatePlayed('')
      setFile(null)
      e.target.reset()
      onUploaded?.()
    } catch (err) {
      setError(err.response?.data?.detail ?? err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 rounded-lg border border-neutral-200 p-4 dark:border-neutral-700">
      <h2 className="text-lg font-semibold">Upload a game</h2>

      <label className="flex flex-col gap-1 text-sm">
        Title
        <input
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="vs. Eastside Warriors"
          className="rounded border border-neutral-300 px-3 py-2 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        Date played
        <input
          required
          type="date"
          value={datePlayed}
          onChange={(e) => setDatePlayed(e.target.value)}
          className="rounded border border-neutral-300 px-3 py-2 dark:border-neutral-600 dark:bg-neutral-800"
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        Video file
        <input
          required
          type="file"
          accept="video/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
      </label>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <button
        type="submit"
        disabled={submitting}
        className="mt-1 rounded bg-orange-600 px-4 py-2 font-medium text-white disabled:opacity-50"
      >
        {submitting ? 'Uploading…' : 'Upload & process'}
      </button>
    </form>
  )
}
