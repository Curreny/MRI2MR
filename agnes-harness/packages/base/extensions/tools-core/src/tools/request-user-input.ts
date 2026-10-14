import { defineTool, type ToolResult } from '@agnes/extension-api'
import { Type } from '@sinclair/typebox'

export const requestUserInputTool = defineTool({
  name: 'request_user_input',
  description:
    'Pause the current task and ask the human to choose an option in the client confirmation dialog. Use for required confirmations, sequence selection and human review. Waits without a time limit; the selected option is returned to this same task. Continue only according to that choice. Cancelled or unavailable means do not proceed or repeat the question automatically. This does not grant tool permissions.',
  parameters: Type.Object(
    {
      question: Type.String({ minLength: 1, maxLength: 2000 }),
      context: Type.Optional(Type.String({ maxLength: 16000 })),
      options: Type.Array(
        Type.Object(
          {
            id: Type.String({ minLength: 1, maxLength: 64, pattern: '^[a-zA-Z0-9_-]+$' }),
            label: Type.String({ minLength: 1, maxLength: 200 }),
            description: Type.Optional(Type.String({ maxLength: 1000 })),
          },
          { additionalProperties: false },
        ),
        { minItems: 2, maxItems: 8 },
      ),
    },
    { additionalProperties: false },
  ),
  meta: {
    isReadOnly: true,
    isDestructive: false,
    isConcurrencySafe: false,
    isOpenWorld: false,
    replay: 'never',
    costHint: {},
    deferLoading: false,
    requiresApproval: 'never',
  },
  async execute(args, ctx): Promise<ToolResult> {
    const result = ctx.requestUserInput
      ? await ctx.requestUserInput(args)
      : { status: 'unavailable' as const }
    return {
      content: [{ type: 'text', text: JSON.stringify(result) }],
      ...(result.status === 'unavailable' ? { isError: true } : {}),
    }
  },
})
