import { mkdtemp, readdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { EventEnvelope } from '@agnes/protocol'
import { afterEach, expect, it, vi } from 'vitest'
import { AgentExecutionLog } from '../src/supervisor/agent-log.js'

const directories: string[] = []
afterEach(async () => {
  for (const directory of directories.splice(0)) await rm(directory, { recursive: true, force: true })
})
async function directory() {
  const path = await mkdtemp(join(tmpdir(), 'agnes-agent-log-'))
  directories.push(path)
  return path
}
const event = (type: string, data: unknown, seq = 1, time = 0, lane = 'main') =>
  ({ type, data, seq, ts: new Date(time).toISOString(), lane }) as Pick<
    EventEnvelope,
    'type' | 'data' | 'seq' | 'lane' | 'ts'
  >
async function records(log: AgentExecutionLog) {
  await log.flush()
  return (await readFile(log.file, 'utf8'))
    .trim()
    .split('\n')
    .map((line) => JSON.parse(line))
}

it('records correlated steps, parameter changes, elapsed time and the media-limit failure without raw conversation or image data', async () => {
  const log = new AgentExecutionLog({ directory: await directory(), clock: () => 0 })
  const name = 'mcp_vessel_pilot_abcdef12_suggest_vessel_parameters'
  log.event('session-a', event('turn/start', { turn: 1 }, 1, 100))
  log.event('session-a', event('step/start', { turn: 1, step: 2 }, 2, 150))
  log.event('session-a', event('user/message', { content: [{ text: 'PRIVATE_PROMPT' }] }, 3, 160))
  log.event(
    'session-a',
    event(
      'tool/call',
      {
        name,
        toolUseId: 'call-1',
        args: {
          case_id: 'case-1',
          based_on_candidate_id: 'round-1',
          parameters: { vessel_threshold: 800 },
          input_path: 'PRIVATE_PATH',
        },
      },
      4,
      200,
    ),
  )
  log.event(
    'session-a',
    event(
      'tool/result',
      {
        toolUseId: 'call-1',
        isError: false,
        content: [
          {
            type: 'text',
            text: JSON.stringify({
              status: 'recommended',
              parameters: { vessel_threshold: 900 },
              changed_parameter: 'vessel_threshold',
              reason: 'reduce density/noise',
            }),
          },
          { type: 'image', data: 'PRIVATE_PIXELS' },
        ],
      },
      5,
      450,
    ),
  )
  log.event('session-b', event('tool/call', { name: 'get_job', toolUseId: 'call-1', args: {} }, 1, 500))
  log.event(
    'session-b',
    event(
      'tool/result',
      {
        toolUseId: 'call-1',
        isError: true,
        content: [
          {
            type: 'text',
            text: 'mcp server vessel-pilot returned invalid content: image count exceeds media limit',
          },
        ],
      },
      2,
      700,
    ),
  )
  log.event('session-a', event('turn/end', { reason: 'completed' }, 6, 800))
  const rows = await records(log)
  expect(rows.find((row) => row.event === 'turn/start')).toMatchObject({
    level: 'INFO',
    sessionId: 'session-a',
    turn: 1,
  })
  expect(rows.find((row) => row.event === 'tool/result' && row.sessionId === 'session-a')).toMatchObject({
    level: 'INFO',
    tool: name,
    turn: 1,
    step: 2,
    durationMs: 250,
    case_id: 'case-1',
    parameters: { vessel_threshold: 900 },
    toolStatus: 'succeeded',
  })
  expect(rows.find((row) => row.level === 'ERROR')).toMatchObject({
    tool: 'get_job',
    toolStatus: 'failed',
    errorSummary: expect.stringContaining('image count exceeds media limit'),
  })
  expect(rows.find((row) => row.event === 'turn/end')).toMatchObject({ durationMs: 700 })
  expect(JSON.stringify(rows)).not.toMatch(/PRIVATE_(PROMPT|PATH|PIXELS)/)
  await log.close()
})

it('filters severities and keeps secret-shaped content out of worker messages and error summaries', async () => {
  const log = new AgentExecutionLog({ directory: await directory(), level: 'warn', clock: () => 0 })
  log.write('info', 'hidden')
  log.worker({
    sessionKey: 'session',
    level: 'warn',
    message: 'Authorization: Bearer private-token password=private-value',
  })
  log.event(
    'session',
    event('effect/settled', { effectId: 'fx', outcome: 'error', code: 'E_PROVIDER', durationMs: 40 }),
  )
  const rows = await records(log)
  expect(rows.map((row) => row.level)).toEqual(['WARN', 'ERROR'])
  expect(JSON.stringify(rows)).not.toMatch(/private-token|private-value/)
  expect(rows[1]).toMatchObject({ code: 'E_PROVIDER', durationMs: 40 })
  await log.close()
})

it('does not duplicate durable events replayed when the daemon starts', async () => {
  const log = new AgentExecutionLog({ directory: await directory(), clock: () => 10_000 })
  log.event('session', event('turn/start', { turn: 1 }, 1, 1_000))
  log.event('session', event('turn/start', { turn: 2 }, 2, 10_000))
  const rows = await records(log)
  expect(rows).toHaveLength(1)
  expect(rows[0]).toMatchObject({ event: 'turn/start', turn: 2 })
  await log.close()
})

it('rotates files and flushes all accepted records on shutdown', async () => {
  const path = await directory()
  const log = new AgentExecutionLog({ directory: path, maxBytes: 250, backups: 2 })
  for (let index = 0; index < 10; index++) log.write('info', `step-${index}`)
  await log.close()
  const files = (await readdir(path)).sort()
  expect(files).toEqual(['agent.jsonl', 'agent.jsonl.1', 'agent.jsonl.2'])
  const last = JSON.parse((await readFile(log.file, 'utf8')).trim().split('\n').at(-1) ?? '{}')
  expect(last.event).toBe('step-9')
  log.write('error', 'after-close')
  expect(await readFile(log.file, 'utf8')).not.toContain('after-close')
})

it('keeps execution alive when the log destination cannot be written', async () => {
  const path = join(await directory(), 'not-a-directory')
  await writeFile(path, 'file')
  const warning = vi.spyOn(process.stderr, 'write').mockImplementation(() => true)
  try {
    const log = new AgentExecutionLog({ directory: path })
    log.write('info', 'event-1')
    log.write('error', 'event-2')
    await expect(log.close()).resolves.toBeUndefined()
    expect(warning).toHaveBeenCalledOnce()
  } finally {
    warning.mockRestore()
  }
})
