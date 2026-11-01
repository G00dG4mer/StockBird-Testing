import { useEffect, useState } from 'react'
import { getShariah, type ShariahCheck, type ShariahProfile } from '../api/stocks'
import { cx } from '../lib/cx'
import { ETHICAL_BADGE } from '../lib/ethical'
import { errorMessage } from '../lib/format'
import { Card, CardBody, CardHeader, Skeleton } from './ui'

/** One ratio as a plain number. The bar spans 0 to 1.5x the reference
 * level; the markers show the levels index providers use. No pass / fail
 * and no good / bad colour - the investor decides. */
function CheckRow({ check }: { check: ShariahCheck }) {
  const scale = check.reference * 1.5
  const width = check.value == null ? 0 : Math.min(100, (check.value / scale) * 100)
  const tick = (check.reference / scale) * 100
  const strictTick = check.strict_reference != null ? (check.strict_reference / scale) * 100 : null
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
        <span className="text-fg/90">
          {check.label} <span className="text-xs text-faint">/ {check.basis}</span>
        </span>
        <span className="tabular shrink-0 font-semibold">{check.value == null ? '—' : `${check.value.toFixed(1)}%`}</span>
      </div>
      <div className="relative h-1.5 rounded-full bg-raised">
        <div className="h-full rounded-full bg-accent/70" style={{ width: `${width}%` }} />
        <div className="absolute -top-0.5 h-2.5 w-px bg-fg/60" style={{ left: `${tick}%` }} title={`Reference ${check.reference}%`} />
        {strictTick != null && (
          <div
            className="absolute -top-0.5 h-2.5 w-px bg-fg/30"
            style={{ left: `${strictTick}%` }}
            title={`Stricter reference ${check.strict_reference}%`}
          />
        )}
      </div>
      <div className="mt-1 text-xs text-faint">
        Reference {check.reference}%{check.strict_reference != null && ` (stricter ${check.strict_reference}%)`}
        {check.note && ` · ${check.note}`}
      </div>
    </div>
  )
}

/** Ethical screen for one stock: what the business does, and its debt,
 * cash and interest-income numbers. Data only, never a verdict. */
export default function ShariahCard({ symbol, market }: { symbol: string; market: string }) {
  const [data, setData] = useState<ShariahProfile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (market === 'crypto') return
    let cancelled = false
    setData(null)
    setError(null)
    getShariah(symbol, market)
      .then((d) => !cancelled && setData(d))
      .catch((err) => !cancelled && setError(errorMessage(err)))
    return () => {
      cancelled = true
    }
  }, [symbol, market])

  if (market === 'crypto') return null

  return (
    <Card id="section-shariah" section="Ethical screen">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            Ethical screen
            {data && (
              <span className={cx('rounded px-1.5 text-xs font-medium', ETHICAL_BADGE[data.business.status])}>
                {data.business.label}
              </span>
            )}
          </span>
        }
        description="What the business does, and its debt and interest numbers. Data only - you decide what fits your values."
      />
      <CardBody className="space-y-5">
        {error ? (
          <p className="text-xs text-faint">Not available: {error}</p>
        ) : !data ? (
          <div className="space-y-3">
            <Skeleton className="h-4 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-full" />
          </div>
        ) : (
          <>
            <div className="rounded-lg bg-canvas p-4">
              <div className="mb-1 text-xs font-medium text-muted">Business activity</div>
              <p className="text-sm text-fg/90">{data.business.reason}</p>
              <p className="mt-1 text-xs text-faint">
                {[data.sector, data.industry].filter(Boolean).join(' · ') || 'Sector not published'}
              </p>
              {data.business.flags.length > 0 && (
                <p className="mt-1 text-xs text-warn">Business description mentions: {data.business.flags.join(', ')}</p>
              )}
            </div>

            {data.checks.length > 0 && (
              <div className="space-y-4">
                {data.checks.map((c) => (
                  <CheckRow key={c.key} check={c} />
                ))}
              </div>
            )}

            <p className="text-[12px] text-faint">
              From {data.source}
              {data.period && `, statements to ${data.period}`}. Ethical business means no excluded activity (alcohol,
              tobacco, gambling, pork, adult content, weapons). Interest is shown as numbers; the markers are the levels
              index providers use, with the stricter level as a second marker. You decide what fits your values.
            </p>
          </>
        )}
      </CardBody>
    </Card>
  )
}
