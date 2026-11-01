import type { ShariahStatus } from '../api/listings'

// Owner's rule: never say halal / haram / compliant, never pass / fail.
// "Ethical business" only means no excluded activity (alcohol, tobacco,
// gambling, pork, adult content, weapons). Interest-based businesses get a
// plain, neutral tag; the investor decides from the numbers.

export const ETHICAL_TAGS: ShariahStatus[] = ['ethical', 'interest', 'mixed', 'excluded', 'unknown']

export const ETHICAL_BADGE: Record<ShariahStatus, string> = {
  ethical: 'bg-up-soft text-up',
  interest: 'bg-raised text-muted',
  mixed: 'bg-raised text-muted',
  excluded: 'bg-warn-soft text-warn',
  unknown: 'bg-raised text-faint',
}

/** English labels, for places that are not translated. */
export const ETHICAL_LABEL: Record<ShariahStatus, string> = {
  ethical: 'Ethical business',
  interest: 'Interest-based business',
  mixed: 'Mixed activity',
  excluded: 'Excluded activity',
  unknown: 'Not classified',
}
