import type { ToolCallItem } from './chat'

export type NodeCategory = 'explore' | 'formalize' | 'writeup' | 'file' | 'other'

// Best-effort label for a tool call, derived only from data we actually have
// (the tool name + its JSON args) — no fabricated stats, no invented stages.
// Falls back to the raw tool name when args don't parse (they can be partial
// while still streaming).
export function describeToolCall(item: ToolCallItem): { label: string; sub?: string; category: NodeCategory } {
  let parsed: Record<string, unknown> | null = null
  try {
    parsed = JSON.parse(item.args)
  } catch {
    parsed = null
  }

  if (item.name === 'Bash') {
    const command = typeof parsed?.command === 'string' ? parsed.command : ''
    if (/openalex|semantic_scholar|crossref|arxiv|core\.py|openaire|web_search/.test(command)) {
      return { label: 'Explore literature', sub: command.slice(0, 90), category: 'explore' }
    }
    if (/lean\.py/.test(command)) {
      return { label: 'Formal check (Lean + Mathlib)', sub: command.slice(0, 90), category: 'formalize' }
    }
    if (/tectonic/.test(command)) {
      return { label: 'Compile write-up (LaTeX)', sub: command.slice(0, 90), category: 'writeup' }
    }
    return { label: 'Shell', sub: command.slice(0, 90), category: 'other' }
  }

  if (item.name === 'Write' || item.name === 'Edit') {
    const path = typeof parsed?.file_path === 'string' ? parsed.file_path : undefined
    return { label: `${item.name} file`, sub: path, category: 'file' }
  }

  if (item.name === 'Read' || item.name === 'Glob' || item.name === 'Grep') {
    const sub =
      (typeof parsed?.file_path === 'string' && parsed.file_path) ||
      (typeof parsed?.pattern === 'string' && parsed.pattern) ||
      undefined
    return { label: item.name, sub, category: 'file' }
  }

  if (item.name === 'AskUserQuestion') {
    return { label: 'Asking a question', category: 'other' }
  }

  return { label: item.name, category: 'other' }
}
