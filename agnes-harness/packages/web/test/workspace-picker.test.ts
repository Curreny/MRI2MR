/** @vitest-environment happy-dom */
import { describe, expect, it, vi } from 'vitest'
import { setLocaleTranslator } from '../src/locale-bridge.js'
import {
  multiFolderPickerAvailable,
  requestMultiFolderPicker,
  requestWorkspacePicker,
  workspacePickerAvailable,
} from '../src/workspace-picker.js'
import { zhT } from './helpers/locale.js'

// i18n: these suites assert zh-CN catalog output; pin the translator before imports run.
setLocaleTranslator(zhT)

describe('workspace picker client', () => {
  it('checks capability without a browser credential', async () => {
    const fetcher = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify({ available: true }), { status: 200 }),
    )
    await expect(workspacePickerAvailable(fetcher)).resolves.toBe(true)
    expect(fetcher).toHaveBeenCalledWith(
      '/api/workspace-picker',
      expect.objectContaining({
        method: 'GET',
        credentials: 'same-origin',
      }),
    )
    expect(fetcher.mock.calls[0]?.[1]?.headers).toBeUndefined()
  })

  it('returns selected and cancelled outcomes and keeps unavailable as a manual fallback', async () => {
    await expect(
      requestWorkspacePicker(
        vi.fn<typeof fetch>(
          async () =>
            new Response(JSON.stringify({ status: 'selected', path: '/tmp/工作区' }), { status: 200 }),
        ),
      ),
    ).resolves.toEqual({ status: 'selected', path: '/tmp/工作区' })
    await expect(
      requestWorkspacePicker(
        vi.fn<typeof fetch>(
          async () => new Response(JSON.stringify({ status: 'cancelled' }), { status: 200 }),
        ),
      ),
    ).resolves.toEqual({ status: 'cancelled' })
    await expect(
      requestWorkspacePicker(
        vi.fn<typeof fetch>(
          async () => new Response(JSON.stringify({ status: 'unavailable' }), { status: 503 }),
        ),
      ),
    ).resolves.toEqual({ status: 'unavailable' })
  })

  it('fails closed on malformed or unauthenticated results', async () => {
    await expect(
      requestWorkspacePicker(
        vi.fn<typeof fetch>(
          async () => new Response(JSON.stringify({ status: 'selected', path: '' }), { status: 200 }),
        ),
      ),
    ).rejects.toThrow('无法确认')
    await expect(
      requestWorkspacePicker(
        vi.fn<typeof fetch>(
          async () =>
            new Response(JSON.stringify({ error: { code: 'UNAUTHORIZED', detail: 'secret' } }), {
              status: 401,
            }),
        ),
      ),
    ).rejects.toThrow('无法确认')
  })
})

describe('multi-folder picker client', () => {
  it('checks capability and returns the backend input attachment without composing a prompt', async () => {
    const attachment = {
      type: 'file',
      name: 'DICOM-1-cases.json',
      mimeType: 'application/vnd.agnes.input+json',
      data: 'e30=',
    }
    const capability = vi.fn<typeof fetch>(
      async () => new Response(JSON.stringify({ available: true }), { status: 200 }),
    )
    await expect(multiFolderPickerAvailable(capability)).resolves.toBe(true)
    expect(capability).toHaveBeenCalledWith(
      '/api/dicom-picker',
      expect.objectContaining({ method: 'GET', credentials: 'same-origin' }),
    )
    await expect(
      requestMultiFolderPicker(
        vi.fn<typeof fetch>(
          async () =>
            new Response(JSON.stringify({ status: 'selected', attachment }), {
              status: 200,
            }),
        ),
      ),
    ).resolves.toEqual({ status: 'selected', attachment })
  })

  it('fails closed for legacy path responses', async () => {
    await expect(
      requestMultiFolderPicker(
        vi.fn<typeof fetch>(
          async () =>
            new Response(JSON.stringify({ status: 'selected', paths: ['C:\\ok', ''] }), {
              status: 200,
            }),
        ),
      ),
    ).rejects.toThrow('无法确认')
  })
  it('reports unreadable directories and treats cancellation as no task', async () => {
    await expect(
      requestMultiFolderPicker(
        async () =>
          new Response(JSON.stringify({ error: { code: 'DICOM_INPUT_UNREADABLE' } }), { status: 422 }),
      ),
    ).rejects.toThrow('无法读取')
    await expect(
      requestMultiFolderPicker(async () => new Response(JSON.stringify({ status: 'cancelled' }))),
    ).resolves.toEqual({ status: 'cancelled' })
  })
})
