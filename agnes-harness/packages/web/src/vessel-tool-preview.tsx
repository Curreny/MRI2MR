import type { ContentBlock, UINode } from '@agnes/protocol'
import type { ClientResourceService, LocaleService, SessionService } from '@agnes/web-client'
import { VesselPreview, type VesselVisualization } from '@agnes/web-ui/assistant-ui'
import { useEffect, useState, useSyncExternalStore } from 'react'

type ToolNode = Extract<UINode, { kind: 'tool' }>
const TOOL =
  /^(?:mcp_vessel_pilot_[a-f0-9]{8}_)?(?:inspect_dicom_case|start_dicom_conversion|get_vessel_job|evaluate_vessel_candidate|finalize_vessel_case|suggest_vessel_parameters)$/
const HASH = /^[a-f0-9]{64}$/
const IMAGE_STAGES = new Set(['dicom', 'nifti', 'candidate'])
const noSubscription = () => () => undefined
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === 'object' && !Array.isArray(value)
const text = (value: unknown): value is string => typeof value === 'string' && value.length <= 2048
const numbers = (value: unknown): value is Record<string, number> =>
  record(value) &&
  Object.keys(value).length <= 32 &&
  Object.entries(value).every(
    ([key, number]) => key.length <= 128 && typeof number === 'number' && Number.isFinite(number),
  )

// The visualization is the first JSON field. Recover that complete field if a large
// output listing was truncated by the tool-output guard after the preview metadata.
function visualizationPayload(source: string): unknown {
  try {
    const value: unknown = JSON.parse(source)
    return record(value) ? value.visualization : undefined
  } catch {
    const prefix = '{"visualization":'
    if (!source.startsWith(prefix)) return undefined
    let depth = 0
    let quoted = false
    let escaped = false
    for (let index = prefix.length; index < Math.min(source.length, 16384); index++) {
      const character = source[index]
      if (quoted) {
        if (escaped) escaped = false
        else if (character === '\\') escaped = true
        else if (character === '"') quoted = false
        continue
      }
      if (character === '"') quoted = true
      else if (character === '{') depth++
      else if (character === '}' && --depth === 0) {
        try {
          return JSON.parse(source.slice(prefix.length, index + 1))
        } catch {
          return undefined
        }
      }
    }
    return undefined
  }
}

export function hasVesselVisualization(node: UINode): boolean {
  return (
    node.kind === 'tool' &&
    TOOL.test(node.name) &&
    node.resultSeq !== undefined &&
    node.resultPreview?.startsWith('{"visualization":') === true
  )
}

/** Validate the data contract and bind every image to a link in this very tool result. */
export function readVesselVisualization(content: readonly ContentBlock[]): VesselVisualization | undefined {
  for (const block of content) {
    if (block.type !== 'text') continue
    const value = visualizationPayload(block.text)
    if (
      !record(value) ||
      value.version !== 1 ||
      !text(value.title) ||
      !text(value.case_id) ||
      !['dicom', 'nifti', 'candidate', 'visual_qc', 'final', 'tuning'].includes(String(value.stage)) ||
      (value.candidate_id != null && !text(value.candidate_id)) ||
      (value.conclusion != null && !['pass', 'fail', 'review'].includes(String(value.conclusion))) ||
      !numbers(value.parameters) ||
      !record(value.metrics) ||
      Object.keys(value.metrics).length > 2 ||
      !Object.entries(value.metrics).every(
        ([key, metric]) =>
          ['artery', 'vein'].includes(key) &&
          record(metric) &&
          ['file_bytes', 'vertices', 'faces'].every(
            (field) =>
              metric[field] === undefined ||
              (typeof metric[field] === 'number' && Number.isFinite(metric[field]) && metric[field] >= 0),
          ),
      ) ||
      !Array.isArray(value.warnings) ||
      value.warnings.length > 16 ||
      !value.warnings.every(text) ||
      !Array.isArray(value.images) ||
      value.images.length > 3 ||
      !value.images.every(
        (image: unknown) =>
          record(image) &&
          text(image.label) &&
          typeof image.sha256 === 'string' &&
          HASH.test(image.sha256) &&
          typeof image.size === 'number' &&
          Number.isSafeInteger(image.size) &&
          image.size > 0 &&
          image.size <= 1024 * 1024 &&
          image.mime === 'image/png' &&
          content.some(
            (link) =>
              link.type === 'resource_link' &&
              link.uri === `artifact://${image.sha256}` &&
              link.mimeType === image.mime,
          ),
      )
    )
      continue
    if (
      value.decision !== undefined &&
      (!record(value.decision) ||
        !['status', 'reason', 'artery_assessment', 'vein_assessment'].every(
          (key) =>
            value.decision &&
            record(value.decision) &&
            (value.decision[key] == null || text(value.decision[key])),
        ) ||
        (value.decision.next_parameters != null && !numbers(value.decision.next_parameters)))
    )
      continue
    return value as VesselVisualization
  }
  return undefined
}

export function VesselToolPreview({
  node,
  session,
  resources,
  locale,
}: {
  node: ToolNode
  session?: SessionService | undefined
  resources?: ClientResourceService | undefined
  locale?: LocaleService | undefined
}) {
  const sessionId = useSyncExternalStore(session?.subscribe ?? noSubscription, () => session?.sessionId)
  const [attempt, setAttempt] = useState(0)
  const owner = `${sessionId}:${node.id}:${node.seq}:${node.resultSeq}:${attempt}`
  const [loaded, setLoaded] = useState<{
    owner: string
    value: VesselVisualization
    images: { label: string; url?: string; unavailable?: boolean }[]
  }>()
  const [failedOwner, setFailedOwner] = useState<string>()
  const eligible = hasVesselVisualization(node)
  useEffect(() => {
    if (!eligible) return
    const handle = session?.handle
    if (!handle?.readToolDetail || !resources || !sessionId) {
      setFailedOwner(owner)
      return
    }
    let active = true
    const abort = new AbortController()
    const releases: (() => void)[] = []
    setLoaded(undefined)
    setFailedOwner(undefined)
    void (async () => {
      const detail = await handle.readToolDetail?.(node.seq, node.resultSeq, { signal: abort.signal })
      if (!active) return
      if (!detail?.result || detail.call.toolUseId !== node.toolUseId || detail.call.name !== node.name)
        throw new Error('Tool result mismatch')
      const value = readVesselVisualization(detail.result.content)
      if (!value) throw new Error('Preview metadata unavailable')
      // Older persisted tool results may still contain the same candidate montage
      // on QC/tuning/finalization cards. Only the first candidate card owns it.
      const visibleImages = IMAGE_STAGES.has(value.stage) ? value.images : []
      setLoaded({ owner, value, images: visibleImages.map(({ label }) => ({ label })) })
      await Promise.all(
        visibleImages.map(async (image, index) => {
          try {
            const resource = await resources.images.load({
              laneId: 'main',
              artifact: { sha256: image.sha256, size: image.size, mime: image.mime },
            })
            if (!active) {
              resource.release()
              return
            }
            releases.push(resource.release)
            setLoaded((previous) =>
              previous?.owner === owner
                ? {
                    ...previous,
                    images: previous.images.map((item, i) =>
                      i === index ? { label: image.label, url: resource.url } : item,
                    ),
                  }
                : previous,
            )
          } catch {
            if (active)
              setLoaded((previous) =>
                previous?.owner === owner
                  ? {
                      ...previous,
                      images: previous.images.map((item, i) =>
                        i === index ? { label: image.label, unavailable: true } : item,
                      ),
                    }
                  : previous,
              )
          }
        }),
      )
    })().catch(() => {
      if (active) setFailedOwner(owner)
    })
    return () => {
      active = false
      abort.abort()
      for (const release of releases) release()
    }
  }, [eligible, owner, node.seq, node.resultSeq, node.toolUseId, node.name, session, sessionId, resources])
  if (!eligible) return null
  const t = (key: string) => locale?.t(key) ?? key
  if (loaded?.owner === owner)
    return <VesselPreview visualization={loaded.value} images={loaded.images} t={t} />
  return (
    <div className="vessel-preview" role="status">
      {t(failedOwner === owner ? 'vessel.unavailable' : 'vessel.loading')}
      {failedOwner === owner && (
        <button type="button" onClick={() => setAttempt(attempt + 1)}>
          {t('vessel.retry')}
        </button>
      )}
    </div>
  )
}
