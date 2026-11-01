import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { getUpdateStatus } from '../api/updates'
import { useSession } from '../lib/session'
import { reportUpdateCheck, useUpdateNotice } from '../lib/updateNotice'
import { Icon } from './ui'

/**
 * Small floating "Update found" card on the right, shown for a few seconds on
 * any page. Reads the server's own GitHub check (Settings -> Updates, automatic
 * or manual) once a minute; never calls GitHub itself.
 */
export default function UpdateNotice() {
  const { t } = useTranslation('app')
  const admin = useSession((s) => s.me?.role === 'admin')
  const notice = useUpdateNotice((s) => s.notice)
  const hide = useUpdateNotice((s) => s.hide)

  useEffect(() => {
    if (!admin) return
    let cancelled = false
    const load = () =>
      getUpdateStatus()
        .then((s) => !cancelled && s.checked_at && reportUpdateCheck(s))
        .catch(() => {})
    load()
    const timer = window.setInterval(load, 60_000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [admin])

  if (!notice) return null
  return (
    <div
      key={notice.id}
      role="status"
      aria-live="polite"
      className="update-notice-in fixed end-4 top-[calc(4rem+env(safe-area-inset-top))] z-[60] flex w-72 max-w-[calc(100vw-2rem)] items-start gap-3 rounded-lg border border-accent/40 bg-raised px-3.5 py-3 text-sm shadow-xl shadow-black/40 md:top-4"
    >
      <span className="mt-0.5 text-accent-fg">
        <Icon name="refresh" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-fg">{t('status.updateFound.title')}</span>
        <span className="block text-xs text-muted">
          {notice.version ? t('status.updateFound.release', { version: notice.version }) : t('status.updateFound.code')}
        </span>
        <Link to="/settings" onClick={hide} className="mt-1 inline-block text-xs font-medium text-accent hover:underline">
          {t('status.updateFound.view')}
        </Link>
      </span>
      <button type="button" onClick={hide} className="text-faint hover:text-fg" aria-label="Dismiss">
        <Icon name="x" />
      </button>
    </div>
  )
}
