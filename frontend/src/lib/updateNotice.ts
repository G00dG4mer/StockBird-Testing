import { create } from 'zustand'
import type { UpdateCheck } from '../api/updates'

/** What the floating "Update found" card shows. */
export interface UpdateNotice {
  id: number
  /** New release version, or null when only newer code on main was found. */
  version: string | null
}

interface UpdateNoticeStore {
  /** The last check (manual or automatic) found a newer version. */
  available: boolean
  notice: UpdateNotice | null
  setAvailable: (available: boolean) => void
  show: (version: string | null) => void
  hide: () => void
}

/** How long the card stays on screen. */
export const NOTICE_MS = 4000

const SEEN_KEY = 'marketmyna.updateNoticeSeen'
let nextId = 1
let timer: number | undefined

export const useUpdateNotice = create<UpdateNoticeStore>((set) => ({
  available: false,
  notice: null,
  setAvailable: (available) => set({ available }),
  show: (version) => {
    window.clearTimeout(timer)
    set({ available: true, notice: { id: nextId++, version } })
    timer = window.setTimeout(() => set({ notice: null }), NOTICE_MS)
  },
  hide: () => {
    window.clearTimeout(timer)
    set({ notice: null })
  },
}))

/** Identifies one new version, so the automatic check announces it only once. */
function versionKey(check: UpdateCheck): string {
  return [check.release_available ? check.latest : '', check.code?.update_available ? check.code.remote_sha : ''].join('|')
}

function readSeen(): string | null {
  try {
    return window.localStorage.getItem(SEEN_KEY)
  } catch {
    return null
  }
}

function writeSeen(key: string) {
  try {
    window.localStorage.setItem(SEEN_KEY, key)
  } catch {
    // Private window or blocked storage: the card may show again next time.
  }
}

/**
 * Feed a check result in. `manual` (the user pressed Check for updates) always
 * shows the card when there is an update; the automatic check shows it once per
 * new version, wherever the user is in the app.
 */
export function reportUpdateCheck(check: UpdateCheck, manual = false) {
  const store = useUpdateNotice.getState()
  if (check.error) return
  if (!check.update_available) {
    store.setAvailable(false)
    return
  }
  const key = versionKey(check)
  if (manual || readSeen() !== key) {
    writeSeen(key)
    store.show(check.release_available ? check.latest : null)
  } else {
    store.setAvailable(true)
  }
}
