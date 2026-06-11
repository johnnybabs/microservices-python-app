import React, { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import { uploadVideo } from '../api'

export default function Upload({ token }) {
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef()

  // UX5: clear any prior confirmation/error when a new file is chosen.
  function chooseFile(f) {
    if (f) {
      setFile(f)
      setStatus(null)
    }
  }

  function handleDrop(e) {
    e.preventDefault()
    setDragging(false)
    const f = e.dataTransfer.files[0]
    if (f && f.type.startsWith('video/')) chooseFile(f)
  }

  async function handleUpload() {
    if (!file) return
    setLoading(true)
    setStatus(null)
    // Capture details before clearing `file` so the confirmation can show them.
    const uploaded = { name: file.name, size: file.size }
    try {
      await uploadVideo(file, token)
      setStatus({ type: 'success', uploaded })
      setFile(null)
    } catch (err) {
      setStatus({ type: 'error', message: err.response?.data || 'Upload failed. Please try again.' })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-xl mx-auto mt-10">
      <h2 className="text-2xl font-bold text-purple-400 mb-2">Upload Video</h2>
      <p className="text-gray-400 mb-6">Upload a video file. We'll extract the audio and email you when it's ready.</p>

      <div
        onDragOver={e => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors
          ${dragging ? 'border-purple-400 bg-purple-900/20' : 'border-gray-700 hover:border-gray-500'}`}
      >
        <input ref={inputRef} type="file" accept="video/*" className="hidden" onChange={e => chooseFile(e.target.files[0])} />
        {file
          ? <p className="text-purple-300">📹 {file.name} ({(file.size / 1e6).toFixed(1)} MB)</p>
          : <p className="text-gray-500">Drag & drop a video file, or click to browse</p>
        }
      </div>

      {/* UX6: single-file guidance. UX7: accepted formats + the real size limit
          (256MB — set by the frontend nginx client_max_body_size, the binding cap). */}
      <p className="text-gray-500 text-xs mt-3">One file at a time. Upload another after your first conversion completes.</p>
      <p className="text-gray-500 text-xs mt-1">Accepts MP4, MOV, MKV, AVI, WebM, M4V · Maximum 256MB</p>

      {file && (
        <button
          onClick={handleUpload}
          disabled={loading}
          className="mt-4 w-full bg-purple-700 hover:bg-purple-600 disabled:opacity-50 rounded-lg py-3 font-semibold transition-colors"
        >
          {loading ? 'Uploading...' : 'Convert to MP3'}
        </button>
      )}

      {/* UX5: rich upload confirmation with file details + link to track progress. */}
      {status?.type === 'success' && (
        <div className="mt-4 p-4 rounded-lg bg-green-900/40 text-green-300">
          <p className="font-semibold">
            Uploaded: {status.uploaded.name} ({(status.uploaded.size / 1e6).toFixed(1)} MB) — converting now.
          </p>
          <p className="text-sm mt-1">You'll receive an email when your audio is ready.</p>
          <p className="text-sm mt-1">
            Track progress on the{' '}
            <Link to="/my-files" className="underline text-green-200 hover:text-green-100">My Conversions</Link> page.
          </p>
        </div>
      )}
      {status?.type === 'error' && (
        <div className="mt-4 p-4 rounded-lg bg-red-900/40 text-red-300">{status.message}</div>
      )}
    </div>
  )
}
