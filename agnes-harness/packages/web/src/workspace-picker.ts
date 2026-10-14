import { type ContentBlock, validateUserAttachments } from '@agnes/protocol'
import { tr } from './locale-bridge.js'

export type WorkspacePickerResult =
  | { status: 'selected'; path: string }
  | { status: 'cancelled' }
  | { status: 'unavailable' }

export type MultiFolderPickerResult =
  | { status: 'selected'; attachment: Extract<ContentBlock, { type: 'file' }> }
  | { status: 'cancelled' }
  | { status: 'unavailable' }

type Fetcher = typeof fetch

export async function workspacePickerAvailable(fetcher: Fetcher = fetch): Promise<boolean> {
  try {
    const response = await fetcher('/api/workspace-picker', {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
    })
    if (!response.ok) return false
    const body = (await response.json()) as { available?: unknown }
    return body.available === true
  } catch {
    return false
  }
}

export async function multiFolderPickerAvailable(fetcher: Fetcher = fetch): Promise<boolean> {
  try {
    const response = await fetcher('/api/dicom-picker', {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
    })
    if (!response.ok) return false
    const body = (await response.json()) as { available?: unknown }
    return body.available === true
  } catch {
    return false
  }
}

export async function requestMultiFolderPicker(fetcher: Fetcher = fetch): Promise<MultiFolderPickerResult> {
  const response = await fetcher('/api/dicom-picker', {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
  })
  let body: { status?: unknown; attachment?: unknown; error?: { code?: string } }
  try {
    body = (await response.json()) as typeof body
  } catch {
    throw new Error(tr('settings.workspacePicker.ambiguous'))
  }
  if (body.error?.code === 'DICOM_INPUT_UNREADABLE')
    throw new Error('后端无法读取所选 DICOM 目录，请检查目录是否存在及访问权限。')
  if (response.ok && body.status === 'cancelled') return { status: 'cancelled' }
  if (body.status === 'unavailable') return { status: 'unavailable' }
  if (response.ok && body.status === 'selected' && body.attachment && typeof body.attachment === 'object') {
    const attachment = body.attachment as Extract<ContentBlock, { type: 'file' }>
    if (attachment.type === 'file' && attachment.mimeType === 'application/vnd.agnes.input+json') {
      validateUserAttachments([attachment])
      return { status: 'selected', attachment }
    }
  }
  throw new Error(tr('settings.workspacePicker.ambiguous'))
}

export async function requestWorkspacePicker(fetcher: Fetcher = fetch): Promise<WorkspacePickerResult> {
  const response = await fetcher('/api/workspace-picker', {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
  })
  let body: { status?: unknown; path?: unknown }
  try {
    body = (await response.json()) as typeof body
  } catch {
    throw new Error(tr('settings.workspacePicker.ambiguous'))
  }
  if (body.status === 'cancelled') return { status: 'cancelled' }
  if (body.status === 'unavailable') return { status: 'unavailable' }
  if (
    response.ok &&
    body.status === 'selected' &&
    typeof body.path === 'string' &&
    body.path.length > 0 &&
    body.path.length <= 4096 &&
    !body.path.includes('\0')
  )
    return { status: 'selected', path: body.path }
  throw new Error(tr('settings.workspacePicker.ambiguous'))
}
