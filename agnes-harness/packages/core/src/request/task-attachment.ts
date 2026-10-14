import { decodeAttachmentData } from '@agnes/protocol-validation'

/** An explicit user task attachment has the same authority as user text, never a system note.
 * Ordinary JSON files remain data. Malformed/unknown task versions remain ordinary attachments.
 */
export function readTaskAttachment(
  block: Record<string, unknown>,
): { instruction?: string; input: string } | undefined {
  const dataOnly = block.mimeType === 'application/vnd.agnes.input+json'
  if ((!dataOnly && block.mimeType !== 'application/vnd.agnes.task+json') || typeof block.data !== 'string')
    return
  try {
    const value = JSON.parse(new TextDecoder().decode(decodeAttachmentData(block.data, 256 * 1024)))
    // Selected inputs carry data only, even if their contents include an instruction field.
    if (dataOnly) {
      if (value?.version === 1 && value.input !== undefined) return { input: JSON.stringify(value.input) }
      return
    }
    if (
      value?.version !== 1 ||
      typeof value.instruction !== 'string' ||
      !value.instruction.trim() ||
      value.instruction.length > 8192 ||
      value.input === undefined
    )
      return
    return { instruction: value.instruction, input: JSON.stringify(value.input) }
  } catch {
    return undefined
  }
}
