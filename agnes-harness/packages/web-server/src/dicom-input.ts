import { constants } from 'node:fs'
import { access, opendir, realpath, stat } from 'node:fs/promises'

/** Local-only input: the launcher and VesselPilot share the same filesystem/account.
 * Keep large datasets in place; persist the selected roots in the session attachment.
 * VesselPilot owns recursive DICOM validation and checks again before conversion.
 */
export async function prepareDicomInput(paths: string[], signal: AbortSignal) {
  const roots: string[] = []
  for (const path of paths) {
    signal.throwIfAborted()
    const root = await realpath(path)
    if (!(await stat(root)).isDirectory()) throw new Error('DICOM input must be a directory')
    await access(root, constants.R_OK)
    const directory = await opendir(root)
    await directory.close()
    if (!roots.includes(root)) roots.push(root)
  }
  signal.throwIfAborted()
  const manifest = {
    version: 1,
    input: { inputMode: 'local-directory', paths: roots, deidentificationConfirmed: false },
  }
  return {
    type: 'file' as const,
    name: `DICOM-${roots.length}-cases.json`,
    mimeType: 'application/vnd.agnes.input+json',
    data: Buffer.from(JSON.stringify(manifest, null, 2), 'utf8').toString('base64'),
  }
}
