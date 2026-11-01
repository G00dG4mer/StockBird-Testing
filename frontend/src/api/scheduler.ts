import { apiClient } from './client'

/** Smart messaging's report file format (server: src/services/smart_file.py). */
export type SmartFile = 'pdf' | 'xlsx' | 'none'

export interface ScheduleConfig {
  enabled: boolean
  interval_minutes: number | null
  time_of_day: string | null
  symbols: string[]
  market: string
  mode: string
  last_run_at: string | null
  last_run_status: string | null
  last_run_summary: string | null
  report_language: string
  report_sections: string[]
  stock_sections: Record<string, string[]>
  channel_languages: Record<string, string>
  mf_codes: string[]
  ideas_market: string
  /** Markets "Stocks matching your screen" scans; empty = ideas_market (picked, or where most stocks trade). */
  ideas_markets: string[]
  ideas_categories: string[]
  ideas_count: number
  /** "Trending for investors": markets picked (empty = the run's stock markets). */
  hot_invest_markets: string[]
  /** Read only: what a run will scan (no market limit here, never locked). */
  hot_invest_scan?: string[]
  hot_invest_limit?: number | null
  hot_invest_locked?: boolean
  smart_enabled: boolean
  smart_top_n: number
  smart_ai_top: number
  smart_email_full: boolean
  /** The report file sent with the short message, built from the ticked sections. */
  smart_file: SmartFile
  /** Channels that get the file: 'email' and/or 'telegram'. */
  smart_file_channels: string[]
  report_base_url: string
  /** what a run covers: any of 'watchlist' | 'portfolio' | 'custom' (custom = `symbols`) */
  sources: RunSource[]
  /** empty = every watchlist */
  watchlist_ids: number[]
  /** empty = every portfolio */
  portfolio_names: string[]
}

export type RunSource = 'watchlist' | 'portfolio' | 'custom'

export interface SourceSymbol {
  symbol: string
  market: string
}

export interface RunSourceCatalog {
  watchlists: Array<{ id: number; name: string; symbols: SourceSymbol[]; funds?: string[] }>
  // funds: mutual fund codes - covered in the report's funds section, not chart-analysed
  portfolios: Array<{ name: string; symbols: SourceSymbol[]; funds?: string[] }>
}

export async function getRunSources(): Promise<RunSourceCatalog> {
  return (await apiClient.get<RunSourceCatalog>('/scheduler/sources')).data
}

/** Mirrors schedule_config.resolve_targets: portfolio, then watchlists,
 * then custom symbols, de-duplicated by market + symbol. */
export function resolveRunTargets(
  sel: { sources: RunSource[]; watchlistIds: number[]; portfolioNames: string[]; symbols: string[]; market: string },
  catalog: RunSourceCatalog | null,
): SourceSymbol[] {
  const out = new Map<string, SourceSymbol>()
  const add = (s: SourceSymbol) => out.set(`${s.market}:${s.symbol}`, s)
  if (catalog && sel.sources.includes('portfolio'))
    catalog.portfolios
      .filter((p) => !sel.portfolioNames.length || sel.portfolioNames.includes(p.name))
      .forEach((p) => p.symbols.forEach(add))
  if (catalog && sel.sources.includes('watchlist'))
    catalog.watchlists
      .filter((w) => !sel.watchlistIds.length || sel.watchlistIds.includes(w.id))
      .forEach((w) => w.symbols.forEach(add))
  if (sel.sources.includes('custom')) sel.symbols.forEach((s) => add({ symbol: s.toUpperCase(), market: sel.market }))
  return [...out.values()]
}

export interface ReportLanguage {
  code: string
  native: string
  english: string
  /** false = labels are AI-translated only (needs an LLM) */
  builtin: boolean
}

export interface ReportSection {
  id: string
  label: string
  description: string
  default: boolean
  /** Shown only in this area of the app (null = both). */
  area?: 'trader' | 'investor' | null
}

export interface ReportOptions {
  languages: ReportLanguage[]
  sections: ReportSection[]
  channels: string[]
  /** Listing categories for "Stocks matching your screen" (server: data/categories.py). */
  categories: string[]
  llm_configured: boolean
  /** Always 'analytics': no calls; stock ideas as a screen, not picks. */
  compliance?: 'analytics'
}

export async function getReportOptions(): Promise<ReportOptions> {
  return (await apiClient.get<ReportOptions>('/scheduler/report-options')).data
}

interface SchedulerStatus {
  running: boolean
  schedule: ScheduleConfig
}

export async function updateSchedulerConfig(
  overrides: Partial<ScheduleConfig>,
): Promise<ScheduleConfig> {
  const res = await apiClient.put<ScheduleConfig>('/scheduler/config', overrides)
  return res.data
}

export async function getSchedulerStatus(): Promise<SchedulerStatus> {
  const res = await apiClient.get<SchedulerStatus>('/scheduler/status')
  return res.data
}

export interface RunNowResult {
  status: string
  results: Array<{ ok: boolean; symbol: string; dashboard?: unknown; error?: string }>
  summary: string
  /** smart runs: token of the saved full report (/r/<token>) */
  report_token?: string | null
}

/**
 * Starts the run on the server, then checks every few seconds until it is
 * done: a run can take minutes (AI calls per stock), longer than a request may
 * stay open behind Cloudflare. Callers show a loading state meanwhile.
 */
export async function runSchedulerNow(): Promise<RunNowResult> {
  await apiClient.post('/scheduler/run-now')
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 4000))
    const state = (await apiClient.get<{ running: boolean; result: RunNowResult | null }>('/scheduler/run-now')).data
    if (!state.running) {
      if (state.result) return state.result
      throw new Error('The run was interrupted (the server restarted). Please run it again.')
    }
  }
}

// ------------------------------------------------------------ smart reports

export interface SmartRow {
  symbol: string
  market: string
  name?: string | null
  error?: string
  price?: number
  change_percent?: number | null
  normal_low?: number
  normal_high?: number
  week_low?: number
  week_high?: number
  rsi?: number
  /** Average true range (14 days) and today's volume vs its 20-day average. */
  atr?: number
  volume_ratio?: number | null
  trend?: string
  valuation?: string | null
  pe?: number | null
  /** Never a call: Bullish / Neutral / Bearish from fundamentals and trend, and
   * the figures behind it (marketmyna/services/outlook.py). Reports saved before
   * this change carry positive / mixed / negative. */
  reading?: 'bullish' | 'neutral' | 'bearish' | 'positive' | 'mixed' | 'negative'
  why?: string
  attention?: number
  reasons?: string[]
  ai?: boolean
  ai_summary?: string | null
}

export interface SavedReportSummary {
  token: string
  title: string
  created_at: string | null
  stock_count: number
}

export interface SavedReport extends SavedReportSummary {
  rows: SmartRow[]
  meta: Record<string, unknown>
}

export async function listReports(limit = 10): Promise<SavedReportSummary[]> {
  return (await apiClient.get<SavedReportSummary[]>('/reports', { params: { limit } })).data
}

export async function getReport(token: string): Promise<SavedReport> {
  return (await apiClient.get<SavedReport>(`/reports/${encodeURIComponent(token)}`)).data
}
