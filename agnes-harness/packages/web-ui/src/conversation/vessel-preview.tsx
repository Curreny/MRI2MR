import { Image } from 'antd'
import type { Translate } from '../locales/index.js'

const assessmentKeys: Record<string, string> = {
  good: 'vessel.good',
  too_dense: 'vessel.tooDense',
  too_sparse: 'vessel.tooSparse',
  uncertain: 'vessel.uncertain',
  scalp_dominant: 'vessel.scalpDominant',
  intracranial_sparse: 'vessel.intracranialSparse',
}
const reasonKeys: Record<string, string> = {
  'reduce density/noise': 'vessel.reduceNoise',
  'recover missing branches': 'vessel.recoverBranches',
  'compare a user-supplied scale/mesh setting': 'vessel.compareSetting',
  'reduce scalp/peripheral vein proxy while reviewing branch retention': 'vessel.reducePeripheral',
  'All requested vessel previews were assessed as good.': 'vessel.allGood',
  "The requested vessel's visual assessment is uncertain.": 'vessel.uncertain',
  'No untried change remains within the requested search space and parameter locks.': 'vessel.noMoreChanges',
  budget_exhausted: 'vessel.budgetExhausted',
}

export type VesselVisualization = {
  version: 1
  stage: string
  title: string
  case_id: string
  candidate_id?: string | null
  parameters: Record<string, number>
  metrics: Record<
    string,
    { file_bytes?: number; vertices?: number; faces?: number; connected_components?: number }
  >
  conclusion?: string | null
  images: { label: string; sha256: string; size: number; mime: string }[]
  warnings: string[]
  decision?: {
    status?: string
    reason?: string
    next_parameters?: Record<string, number>
    artery_assessment?: string
    vein_assessment?: string
  }
}

/** Pure view: only the host can resolve session-authorized artifact URLs. */
export function VesselPreview({
  visualization: value,
  images,
  t,
}: {
  visualization: VesselVisualization
  images: { label: string; url?: string; unavailable?: boolean }[]
  t: Translate
}) {
  const assessment = (value: string) => (assessmentKeys[value] ? t(assessmentKeys[value]) : value)
  const reason = value.decision?.reason ?? value.decision?.status
  return (
    <section className="vessel-preview" data-vessel-stage={value.stage} aria-label={value.title}>
      <header className="vessel-preview-heading">
        <strong>{value.title}</strong>
        {value.conclusion && (
          <span className="vessel-qc" data-conclusion={value.conclusion}>
            {t('vessel.technicalQc')}: {t(value.conclusion === 'pass' ? 'vessel.pass' : 'vessel.fail')}
          </span>
        )}
      </header>
      <p className="vessel-preview-identity">
        {value.case_id}
        {value.candidate_id ? ` / ${value.candidate_id}` : ''}
      </p>
      <div className="vessel-parameter-summary">
        {['vessel_threshold', 'mrv_weak_grow_tolerance', 'mrv_post_process_min_size']
          .filter((key) => key in value.parameters)
          .map((key) => (
            <span key={key}>
              {key}: <b>{value.parameters[key]}</b>
            </span>
          ))}
      </div>
      <Image.PreviewGroup>
        <div className="vessel-preview-gallery">
          {images.map((image) => (
            <figure key={image.label}>
              {image.url ? (
                <Image src={image.url} alt={image.label} width="100%" />
              ) : (
                <p role="status">
                  {t(image.unavailable ? 'conversation.imageUnavailable' : 'vessel.loading')}
                </p>
              )}
              <figcaption>{image.label}</figcaption>
            </figure>
          ))}
        </div>
      </Image.PreviewGroup>
      {Object.keys(value.metrics).length > 0 && (
        <div className="vessel-metrics-scroll">
          <table className="vessel-metrics">
            <thead>
              <tr>
                <th>{t('vessel.model')}</th>
                <th>GLB</th>
                <th>{t('vessel.vertices')}</th>
                <th>{t('vessel.faces')}</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(value.metrics).map(([name, metric]) => (
                <tr key={name}>
                  <th>{t(name === 'artery' ? 'vessel.artery' : 'vessel.vein')}</th>
                  <td>
                    {typeof metric.file_bytes === 'number'
                      ? `${(metric.file_bytes / 1024 / 1024).toFixed(2)} MB`
                      : '—'}
                  </td>
                  <td>{metric.vertices?.toLocaleString() ?? '—'}</td>
                  <td>{metric.faces?.toLocaleString() ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {Object.keys(value.parameters).length > 0 && (
        <details className="vessel-parameters">
          <summary>{t('vessel.parameters')}</summary>
          <dl>
            {Object.entries(value.parameters).map(([name, parameter]) => (
              <div key={name}>
                <dt>{name}</dt>
                <dd>{parameter}</dd>
              </div>
            ))}
          </dl>
        </details>
      )}
      {value.decision && (
        <div className="vessel-decision">
          <strong>{t('vessel.decision')}</strong>
          <p>
            {[
              value.decision.artery_assessment &&
                `${t('vessel.artery')}: ${assessment(value.decision.artery_assessment)}`,
              value.decision.vein_assessment &&
                `${t('vessel.vein')}: ${assessment(value.decision.vein_assessment)}`,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
          <p>{reason && reasonKeys[reason] ? t(reasonKeys[reason]) : reason}</p>
          {value.decision.next_parameters && (
            <dl>
              {Object.entries(value.decision.next_parameters)
                .filter(([name, parameter]) => parameter !== value.parameters[name])
                .map(([name, parameter]) => (
                  <div key={name}>
                    <dt>{name}</dt>
                    <dd>
                      {value.parameters[name] ?? '—'} → {parameter}
                    </dd>
                  </div>
                ))}
            </dl>
          )}
        </div>
      )}
      {value.warnings.map((warning) => (
        <p className="vessel-preview-note" key={warning}>
          {warning}
        </p>
      ))}
      {['candidate', 'final', 'tuning'].includes(value.stage) && (
        <p className="vessel-preview-note">{t('vessel.meshNote')}</p>
      )}
    </section>
  )
}
