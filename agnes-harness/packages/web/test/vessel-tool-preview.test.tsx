/** @vitest-environment happy-dom */
import { Context } from '@agnes/cordis'
import type { ContentBlock, UINode, UITurn } from '@agnes/protocol'
import { type ClientResourceService, SessionService } from '@agnes/web-client'
import {
  AssistantRuntimeProvider,
  createConversationProjectionStore,
  useConversationRuntime,
} from '@agnes/web-ui/assistant-ui'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WebConversationMessages } from '../src/conversation-message-adapter.js'
import { readVesselVisualization, VesselToolPreview } from '../src/vessel-tool-preview.js'
import { zhLocaleService } from './helpers/locale.js'

const hash = 'a'.repeat(64)
const visualization = (candidate = 'round-1', threshold = 800) => ({
  version: 1,
  stage: 'candidate',
  title: '候选评估 · GLB 六视图',
  case_id: 'case-test',
  candidate_id: candidate,
  parameters: { vessel_threshold: threshold },
  metrics: { artery: { file_bytes: 2048, vertices: 100, faces: 150 } },
  conclusion: 'pass',
  warnings: [],
  images: [{ label: '动脉六视图', sha256: hash, size: 24, mime: 'image/png' }],
})
const content = (value = visualization()): ContentBlock[] => [
  { type: 'text', text: JSON.stringify({ visualization: value }) },
  { type: 'resource_link', uri: `artifact://${hash}`, mimeType: 'image/png', name: 'image' },
]
const node = (id = 'round-1', threshold = 800): Extract<UINode, { kind: 'tool' }> => ({
  kind: 'tool',
  id,
  toolUseId: id,
  seq: id === 'round-1' ? 2 : 4,
  resultSeq: id === 'round-1' ? 3 : 5,
  name: 'mcp_vessel_pilot_12345678_evaluate_vessel_candidate',
  status: 'completed',
  summary: 'evaluate',
  // The actual UI projection is clipped to 4096 characters; the gallery must read durable detail.
  resultPreview: JSON.stringify({ visualization: visualization(id, threshold) }).slice(0, 80),
})
let host: HTMLDivElement
let root: Root
let ctx: Context
let session: SessionService
const release = vi.fn()
const load = vi.fn(
  async (): Promise<{ url: string; release: () => void }> => ({ url: 'blob:preview', release }),
)
const readToolDetail = vi.fn(async (seq: number) => {
  const tool = node(seq === 2 ? 'round-1' : 'round-2')
  return {
    call: { name: tool.name, toolUseId: tool.toolUseId },
    result: { content: content(visualization(tool.id, seq === 2 ? 800 : 850)) },
  }
})
const resources = { images: { load } } as unknown as ClientResourceService
beforeEach(() => {
  Object.defineProperty(globalThis, 'IS_REACT_ACT_ENVIRONMENT', { configurable: true, value: true })
  vi.clearAllMocks()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  ctx = new Context()
  session = new SessionService(ctx, 'session', {
    sessions: { get: (id: string) => ({ id, listeners: new Set(), readToolDetail }) },
  } as never)
})
afterEach(async () => {
  await act(async () => root.unmount())
  await ctx.fiber.dispose()
  host.remove()
})

it('rejects missing result links, oversized images and invalid metadata', () => {
  expect(readVesselVisualization(content())?.candidate_id).toBe('round-1')
  expect(readVesselVisualization(content({ ...visualization(), conclusion: 'review' }))?.conclusion).toBe(
    'review',
  )
  expect(readVesselVisualization(content({ ...visualization(), stage: 'visual_qc' }))?.stage).toBe(
    'visual_qc',
  )
  expect(readVesselVisualization(content().slice(0, 1))).toBeUndefined()
  const value = visualization()
  if (value.images[0]) value.images[0].size = 1024 * 1024 + 1
  expect(readVesselVisualization(content(value))).toBeUndefined()
  expect(readVesselVisualization([{ type: 'text', text: '{invalid' }])).toBeUndefined()
  const guarded = content()
  guarded[0] = {
    type: 'text',
    text: `${JSON.stringify({ visualization: visualization() }).slice(0, -1)},"outputs":["truncated`,
  }
  expect(readVesselVisualization(guarded)?.candidate_id).toBe('round-1')
})

it('keeps both candidate galleries visible after the turn is collapsed and releases them on unmount', async () => {
  const first = node()
  const second = node('round-2', 850)
  const answer: UINode = { kind: 'assistant', id: 'answer', seq: 6, text: '完成' }
  const turn: UITurn = {
    id: 'turn',
    turn: 1,
    startSeq: 1,
    startedAt: '2026-10-13T00:00:00Z',
    endedAt: '2026-10-13T00:01:00Z',
    status: 'completed',
    nodeIds: [first.id, second.id, answer.id],
    finalAssistantId: answer.id,
    inherited: false,
    forkable: false,
    usage: {
      totals: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, reasoning: 0 },
      reasoningComplete: true,
      billingComplete: true,
      calls: [],
    },
  }
  const store = createConversationProjectionStore({
    sessionId: 'session',
    nodes: [first, second, answer],
    turns: [turn],
  })
  function Harness() {
    return createElement(
      AssistantRuntimeProvider,
      { runtime: useConversationRuntime(store) },
      createElement(WebConversationMessages, {
        turns: [turn],
        session,
        resources,
        locale: zhLocaleService(),
      }),
    )
  }
  await act(async () => root.render(createElement(Harness)))
  const cards = host.querySelectorAll('[data-vessel-stage="candidate"]')
  expect(cards).toHaveLength(2)
  expect(cards[0]?.textContent).toContain('800')
  expect(cards[1]?.textContent).toContain('850')
  for (const card of cards) expect(card.closest('[hidden]')).toBeNull()
  expect(host.querySelectorAll('img[src="blob:preview"]')).toHaveLength(2)
  expect(load).toHaveBeenCalledWith({
    laneId: 'main',
    artifact: { sha256: hash, size: 24, mime: 'image/png' },
  })
  expect(readToolDetail).toHaveBeenCalledWith(2, 3, { signal: expect.any(AbortSignal) })
  await act(async () => root.unmount())
  expect(release).toHaveBeenCalledTimes(2)
  root = createRoot(host)
})

it('reports an inaccessible artifact without hiding parameters or failing the chat', async () => {
  load.mockRejectedValueOnce(new Error('forbidden'))
  await act(async () =>
    root.render(
      createElement(VesselToolPreview, { node: node(), session, resources, locale: zhLocaleService() }),
    ),
  )
  expect(host.textContent).toContain('图片无法显示')
  expect(host.textContent).toContain('800')
})

it('renders a saved candidate awaiting visual review', async () => {
  const tool = node()
  readToolDetail.mockResolvedValueOnce({
    call: { name: tool.name, toolUseId: tool.toolUseId },
    result: { content: content({ ...visualization(), conclusion: 'review' }) },
  })
  await act(async () =>
    root.render(
      createElement(VesselToolPreview, { node: tool, session, resources, locale: zhLocaleService() }),
    ),
  )
  expect(host.querySelector('[data-conclusion="review"]')?.textContent).toContain('待复核')
  expect(host.querySelector('img[src="blob:preview"]')).not.toBeNull()
  expect(host.textContent).not.toContain('预览暂不可用')
})

it.each(['visual_qc', 'tuning', 'final'])(
  'does not reload or render duplicate images from the %s stage',
  async (stage) => {
    const tool = node()
    readToolDetail.mockResolvedValueOnce({
      call: { name: tool.name, toolUseId: tool.toolUseId },
      // Keep an image in this payload to cover conversations saved before the
      // backend stopped attaching duplicate montages.
      result: { content: content({ ...visualization(), stage }) },
    })
    await act(async () =>
      root.render(
        createElement(VesselToolPreview, { node: tool, session, resources, locale: zhLocaleService() }),
      ),
    )
    expect(host.querySelector(`[data-vessel-stage="${stage}"]`)).not.toBeNull()
    expect(host.querySelector('img')).toBeNull()
    expect(load).not.toHaveBeenCalled()
  },
)

it('releases late images and never paints them after a session switch', async () => {
  let resolveImage: ((image: { url: string; release: () => void }) => void) | undefined
  const lateRelease = vi.fn()
  load.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        resolveImage = resolve
      }),
  )
  await act(async () =>
    root.render(
      createElement(VesselToolPreview, { node: node(), session, resources, locale: zhLocaleService() }),
    ),
  )
  expect(host.querySelector('img')).toBeNull()
  await act(async () => session.setSession(undefined))
  await act(async () => resolveImage?.({ url: 'blob:old-session', release: lateRelease }))
  expect(host.querySelector('img')).toBeNull()
  expect(lateRelease).toHaveBeenCalledOnce()
})
