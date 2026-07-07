import { useState } from 'react'

function getInitials(name) {
  if (!name) return '?'
  const parts = name.trim().split(/\s+/).slice(0, 2)
  const initials = parts.map((p) => p[0]).join('')
  return initials.toUpperCase() || '?'
}

// Shared avatar with initials fallback. Uses referrerPolicy="no-referrer" because
// Google profile photos (lh3.googleusercontent.com) frequently 403/429 requests
// that carry a cross-origin Referer header.
export default function Avatar({ src, name, className = 'w-8 h-8', textClassName = 'text-sm' }) {
  const [failed, setFailed] = useState(false)

  if (src && !failed) {
    return (
      <img
        src={src}
        alt={name}
        referrerPolicy="no-referrer"
        onError={() => setFailed(true)}
        className={`${className} [border-radius:50%] ring-1 ring-slate-700 object-cover`}
      />
    )
  }

  return (
    <div
      className={`${className} [border-radius:50%] bg-emerald-600/20 ring-1 ring-emerald-600/40 flex items-center justify-center shrink-0`}
    >
      <span className={`text-emerald-400 font-medium ${textClassName}`}>
        {getInitials(name)}
      </span>
    </div>
  )
}
