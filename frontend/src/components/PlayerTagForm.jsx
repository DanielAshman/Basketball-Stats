import { useState } from 'react'

export default function PlayerTagForm({ detection, onSave, onCancel }) {
  const [jersey, setJersey] = useState(detection.player_jersey_number ?? detection.estimated_jersey_number ?? '')
  const [name, setName] = useState(detection.player_name ?? '')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    e.stopPropagation()
    if (jersey === '') return
    setSaving(true)
    try {
      await onSave(detection.id, Number(jersey), name.trim())
    } finally {
      setSaving(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      onClick={(e) => e.stopPropagation()}
      className="absolute z-10 flex flex-col gap-1 rounded border border-neutral-300 bg-white p-2 text-xs shadow-lg dark:border-neutral-600 dark:bg-neutral-800"
      style={{ top: '100%', left: 0, marginTop: 4 }}
    >
      <label className="flex flex-col gap-0.5">
        Jersey #
        <input
          autoFocus
          type="number"
          min="0"
          max="99"
          value={jersey}
          onChange={(e) => setJersey(e.target.value)}
          className="w-16 rounded border border-neutral-300 px-1 py-0.5 dark:border-neutral-600 dark:bg-neutral-700"
        />
      </label>
      <label className="flex flex-col gap-0.5">
        Name (optional)
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-32 rounded border border-neutral-300 px-1 py-0.5 dark:border-neutral-600 dark:bg-neutral-700"
        />
      </label>
      <div className="mt-1 flex gap-1">
        <button
          type="submit"
          disabled={saving || jersey === ''}
          className="rounded bg-orange-600 px-2 py-0.5 text-white disabled:opacity-40"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onCancel()
          }}
          className="rounded border border-neutral-300 px-2 py-0.5 dark:border-neutral-600"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
