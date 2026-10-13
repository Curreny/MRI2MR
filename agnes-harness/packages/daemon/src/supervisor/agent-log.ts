import { appendFile, mkdir, rename, stat, unlink } from 'node:fs/promises'
import { join } from 'node:path'
import { looksLikeSecret } from '@agnes/error-sanitization'
import type { EventEnvelope } from '@agnes/protocol'

export type AgentLogLevel = 'debug' | 'info' | 'warn' | 'error'
const RANK: Record<AgentLogLevel | 'off', number> = { debug: 0, info: 1, warn: 2, error: 3, off: 4 }
type Fields = Record<string, string | number | boolean | Record<string, number>>
type Call = { name: string; started: number; fields: Fields }
type Lane = { turn?: number; step?: number; started?: number }
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {}

function safeText(value: string): string {
  const text = Array.from(value.slice(0, 2048), (character) => {
    const code = character.codePointAt(0) ?? 0
    return code <= 31 || code === 127 ? ' ' : character
  })
    .join('')
    .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
    .replace(
      /((?:api[_-]?key|token|password|secret|authorization)["']?\s*[=:]\s*["']?)[^\s,;"'}]+/gi,
      '$1[redacted]',
    )
  const scan = text.replace(/\bmcp_([a-z0-9_]+)_[a-f0-9]{8}_([A-Za-z0-9_]+)/g, 'mcp_$1_$2')
  return looksLikeSecret(scan) ? '[redacted: credential-shaped content]' : text
}

function identifiers(value: Record<string, unknown>): Fields {
  const fields: Fields = {}
  for (const key of [
    'case_id',
    'candidate_id',
    'job_id',
    'target',
    'conversion_mode',
    'status',
    'phase',
    'conclusion',
    'based_on_candidate_id',
    'changed_parameter',
    'artery_assessment',
    'vein_assessment',
  ]) {
    const item = value[key]
    if (typeof item === 'string' && /^[A-Za-z0-9_.-]{1,128}$/.test(item)) fields[key] = safeText(item)
  }
  for (const key of ['elapsed_seconds', 'elapsed_minutes', 'candidate_count', 'max_candidates']) {
    if (typeof value[key] === 'number' && Number.isFinite(value[key])) fields[key] = value[key]
  }
  const parameters: Record<string, number> = {}
  for (const [name, item] of Object.entries(object(value.parameters)).slice(0, 32)) {
    if (
      /^[a-z][a-z0-9_]{0,63}$/.test(name) &&
      !/key|token|secret|password/.test(name) &&
      typeof item === 'number' &&
      Number.isFinite(item)
    )
      parameters[name] = item
  }
  if (Object.keys(parameters).length) fields.parameters = parameters
  return fields
}

/** Diagnostic projection of committed execution events; the session ledger stays authoritative. */
export class AgentExecutionLog {
  readonly file: string
  private readonly minimum: number
  private readonly calls = new Map<string, Call>()
  private readonly lanes = new Map<string, Lane>()
  private pending: Promise<void> = Promise.resolve()
  private queued = 0
  private dropped = 0
  private reportedFailure = false
  private closed = false
  private bytes: number | undefined
  private readonly startedAt: number

  constructor(
    private readonly options: {
      directory: string
      level?: string | undefined
      maxBytes?: number
      backups?: number
      clock?: () => number
      console?: (line: string) => void
    },
  ) {
    this.file = join(options.directory, 'agent.jsonl')
    this.minimum = RANK[options.level as keyof typeof RANK] ?? RANK.info
    this.startedAt = this.now()
  }

  write(level: AgentLogLevel, event: string, sessionId?: string, fields: Fields = {}): void {
    if (this.closed || RANK[level] < this.minimum) return
    if (this.queued >= 1024) {
      this.dropped++
      return
    }
    const safeFields = Object.fromEntries(
      Object.entries(fields).map(([key, value]) => [
        key,
        typeof value === 'string' ? safeText(value) : value,
      ]),
    )
    const row = `${JSON.stringify({
      ...safeFields,
      ts: new Date(this.now()).toISOString(),
      level: level.toUpperCase(),
      event: safeText(event),
      ...(sessionId ? { sessionId: safeText(sessionId) } : {}),
    })}\n`
    this.queued++
    this.pending = this.pending
      .then(async () => {
        if (this.dropped) {
          const count = this.dropped
          this.dropped = 0
          await this.append(
            `${JSON.stringify({
              ts: new Date(this.now()).toISOString(),
              level: 'WARN',
              event: 'logger.dropped',
              count,
            })}\n`,
          )
        }
        await this.append(row)
        this.options.console?.(row.trimEnd())
      })
      .catch((error: unknown) => {
        if (!this.reportedFailure) {
          this.reportedFailure = true
          // Neither a filesystem failure nor a throwing console sink may affect execution.
          try {
            process.stderr.write(
              `[agent-log] write failed (${String(object(error).code ?? 'IO_ERROR')}); agent execution continues\n`,
            )
          } catch {
            /* advisory only */
          }
        }
      })
      .finally(() => {
        this.queued--
      })
  }

  private now(): number {
    return this.options.clock?.() ?? Date.now()
  }

  private async append(row: string): Promise<void> {
    await mkdir(this.options.directory, { recursive: true })
    this.bytes ??= await stat(this.file).then(
      (value) => value.size,
      () => 0,
    )
    const length = Buffer.byteLength(row)
    if (this.bytes > 0 && this.bytes + length > (this.options.maxBytes ?? 10 * 1024 * 1024)) {
      const backups = this.options.backups ?? 5
      for (let index = backups; index >= 1; index--) {
        const from = index === 1 ? this.file : `${this.file}.${index - 1}`
        const to = `${this.file}.${index}`
        await unlink(to).catch((error) => {
          if (error.code !== 'ENOENT') throw error
        })
        await rename(from, to).catch((error) => {
          if (error.code !== 'ENOENT') throw error
        })
      }
      this.bytes = 0
    }
    await appendFile(this.file, row, { encoding: 'utf8', mode: 0o600 })
    this.bytes += length
  }

  event(sessionId: string, event: Pick<EventEnvelope, 'type' | 'data' | 'seq' | 'lane' | 'ts'>): void {
    try {
      const data = object(event.data)
      const eventTime = Number.isFinite(Date.parse(event.ts)) ? Date.parse(event.ts) : this.now()
      // Workers replay their durable ledger after a daemon restart. Those events are already
      // available in the session record and would otherwise be duplicated on every restart.
      if (eventTime < this.startedAt - 1_000) return
      const laneId = event.lane ?? 'main'
      const laneKey = `${sessionId}\0${laneId}`
      const lane = this.lanes.get(laneKey) ?? {}
      if (event.type === 'turn/start') {
        lane.turn = Number(data.turn)
        lane.started = eventTime
        delete lane.step
      }
      if (event.type === 'step/start') {
        lane.turn = Number(data.turn)
        lane.step = Number(data.step)
      }
      if (['turn/start', 'step/start'].includes(event.type)) {
        if (this.lanes.size >= 4096 && !this.lanes.has(laneKey))
          this.lanes.delete(this.lanes.keys().next().value as string)
        this.lanes.set(laneKey, lane)
      }
      const fields: Fields = { lane: laneId, seq: event.seq, eventTs: event.ts }
      if (lane.turn !== undefined) fields.turn = lane.turn
      if (lane.step !== undefined) fields.step = lane.step
      let level: AgentLogLevel = 'info'
      const callKey = `${laneKey}\0${data.toolUseId}`
      if (event.type === 'tool/call') {
        const name = safeText(String(data.name ?? 'unknown'))
        const args = name.includes('vessel_pilot') ? identifiers(object(data.args)) : {}
        if (this.calls.size >= 4096) this.calls.delete(this.calls.keys().next().value as string)
        this.calls.set(callKey, { name, started: eventTime, fields: args })
        Object.assign(fields, args, { tool: name, toolUseId: safeText(String(data.toolUseId)) })
      } else if (event.type === 'tool/result') {
        const call = this.calls.get(callKey)
        this.calls.delete(callKey)
        if (call)
          Object.assign(fields, call.fields, {
            tool: call.name,
            durationMs: Math.max(0, eventTime - call.started),
          })
        fields.toolUseId = safeText(String(data.toolUseId))
        const cancelled = data.cancelledBy || data.code === 'CANCELLED' || data.code === 'ABORTED'
        fields.toolStatus = cancelled ? 'cancelled' : data.isError ? 'failed' : 'succeeded'
        if (cancelled) level = 'warn'
        else if (data.isError) level = 'error'
        if (typeof data.code === 'string') fields.code = safeText(data.code)
        const blocks = Array.isArray(data.content) ? data.content.map(object) : []
        fields.imageCount = blocks.filter(
          (block) => block.type === 'resource_link' && String(block.mimeType).startsWith('image/'),
        ).length
        const text = blocks.find((block) => block.type === 'text')?.text
        if (typeof text === 'string') {
          if (call?.name.includes('vessel_pilot')) {
            try {
              const result = object(JSON.parse(text))
              Object.assign(fields, identifiers(result), identifiers(object(result.result)))
              if (typeof result.reason === 'string') fields.decisionReason = safeText(result.reason)
              const visualization = object(result.visualization)
              if (typeof visualization.stage === 'string') fields.previewStage = safeText(visualization.stage)
              const error = object(result.error)
              if (typeof error.code === 'string') fields.code = safeText(error.code)
            } catch {
              /* A truncated result still has its call identity and status. */
            }
          }
          if (data.isError) fields.errorSummary = safeText(text)
        }
      } else if (event.type === 'turn/end') {
        fields.reason = safeText(String(data.reason))
        if (lane.started !== undefined) fields.durationMs = Math.max(0, eventTime - lane.started)
        const error = object(data.error)
        if (data.reason === 'error') level = 'error'
        else if (['aborted', 'blocked', 'budget', 'max_steps', 'interrupted'].includes(String(data.reason)))
          level = 'warn'
        if (typeof error.code === 'string') fields.code = safeText(error.code)
        if (typeof error.message === 'string') fields.errorSummary = safeText(error.message)
        this.lanes.delete(laneKey)
        for (const key of this.calls.keys()) if (key.startsWith(`${laneKey}\0`)) this.calls.delete(key)
      } else if (event.type === 'approval/asked') {
        level = 'warn'
      } else if (event.type === 'effect/intent' || event.type === 'effect/settled') {
        level = 'debug'
        for (const key of ['effectId', 'kind', 'outcome', 'code'])
          if (typeof data[key] === 'string') fields[key] = safeText(data[key])
        if (typeof data.durationMs === 'number') fields.durationMs = data.durationMs
        if (data.outcome === 'error') level = 'error'
        else if (data.outcome === 'aborted' || data.outcome === 'unknown') level = 'warn'
      } else if (event.type === 'request/sent' || event.type === 'cost/ledger') {
        level = 'debug'
        for (const key of ['model', 'purpose'])
          if (typeof data[key] === 'string') fields[key] = safeText(data[key])
      } else if (
        ![
          'session/start',
          'turn/start',
          'step/start',
          'step/end',
          'approval/decided',
          'assistant/message',
          'plan.items',
          'artifact/job',
        ].includes(event.type)
      ) {
        level = 'debug'
      }
      this.write(level, event.type, sessionId, fields)
    } catch {
      /* Observation must never break committed-event delivery. */
    }
  }

  worker(input: { sessionKey: string; level: AgentLogLevel; message: string }): void {
    this.write(input.level, 'worker.log', input.sessionKey, { message: safeText(input.message) })
  }

  async flush(): Promise<void> {
    await this.pending
  }
  async close(): Promise<void> {
    this.closed = true
    await this.flush()
    this.calls.clear()
    this.lanes.clear()
  }
}
