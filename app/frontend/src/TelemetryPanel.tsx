import { useState } from 'react'
import type { AssistantTextItem, TimelineItem, ToolCallItem } from './chat'
import { describeToolCall } from './pipelineView'

type Props = {
  items: TimelineItem[]
  tokens: { input: number; output: number } | null
  elapsed: number
  running: boolean
}

export default function TelemetryPanel({ items, tokens, elapsed, running }: Props) {
  const [tab, setTab] = useState<'thoughts' | 'tools'>('thoughts')

  const thoughts = items.filter((i): i is AssistantTextItem => i.kind === 'assistant_text')
  const tools = items.filter((i): i is ToolCallItem => i.kind === 'tool_call')

  return (
    <aside className="telemetry">
      <div className="telemetry__head">
        <span className="telemetry__title">Agent Trace</span>
        {running && <span className="telemetry__live">LIVE</span>}
      </div>

      <div className="telemetry__tabs">
        <button
          className={`telemetry__tab ${tab === 'thoughts' ? 'telemetry__tab--active' : ''}`}
          onClick={() => setTab('thoughts')}
        >
          Thought Trace
        </button>
        <button
          className={`telemetry__tab ${tab === 'tools' ? 'telemetry__tab--active' : ''}`}
          onClick={() => setTab('tools')}
        >
          Tool Calls ({tools.length})
        </button>
      </div>

      <div className="telemetry__body">
        {tab === 'thoughts' &&
          (thoughts.length === 0 ? (
            <div className="telemetry__empty">No reasoning yet.</div>
          ) : (
            thoughts.map((t) => (
              <p key={t.id} className="telemetry__thought">
                {t.segments.join('') || '…'}
              </p>
            ))
          ))}

        {tab === 'tools' &&
          (tools.length === 0 ? (
            <div className="telemetry__empty">No tool calls yet.</div>
          ) : (
            tools.map((t) => {
              const { label, sub } = describeToolCall(t)
              return (
                <div key={t.id} className="telemetry__tool">
                  <div className="telemetry__tool-head">
                    <span>{label}</span>
                    <span className={`telemetry__pill telemetry__pill--${t.done ? 'done' : 'active'}`}>
                      {t.awaiting ? 'awaiting' : t.done ? 'done' : 'running'}
                    </span>
                  </div>
                  {sub && <div className="telemetry__tool-sub">{sub}</div>}
                  {t.result && <pre className="telemetry__tool-result">{t.result.slice(0, 400)}</pre>}
                </div>
              )
            })
          ))}
      </div>

      <div className="telemetry__foot">
        <span>{elapsed.toFixed(1)}s</span>
        {tokens && <span>↓ {tokens.output.toLocaleString()} tok</span>}
        <span>{tools.length} tool calls</span>
      </div>
    </aside>
  )
}
