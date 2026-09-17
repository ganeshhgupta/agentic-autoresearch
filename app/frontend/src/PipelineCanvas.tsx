import type { TimelineItem } from './chat'
import { describeToolCall } from './pipelineView'

type Props = { items: TimelineItem[]; running: boolean }

type NodeStatus = 'done' | 'active' | 'pending'

function nodeFor(item: TimelineItem): { label: string; sub?: string; status: NodeStatus; kind: string } {
  if (item.kind === 'user') {
    return { label: 'Prompt', sub: item.text.slice(0, 90), status: 'done', kind: 'prompt' }
  }
  if (item.kind === 'assistant_text') {
    const text = item.segments.join('').trim()
    return {
      label: 'Reasoning',
      sub: text.slice(0, 140) || undefined,
      status: item.done ? 'done' : 'active',
      kind: 'reasoning',
    }
  }
  const { label, sub, category } = describeToolCall(item)
  const status: NodeStatus = item.awaiting ? 'active' : item.done ? 'done' : 'active'
  return { label, sub, status, kind: category }
}

export default function PipelineCanvas({ items, running }: Props) {
  if (items.length === 0) {
    return (
      <div className="canvas">
        <div className="canvas__empty">
          Send a research question in the Chat tab — the agent's steps will appear here as it works.
        </div>
      </div>
    )
  }

  return (
    <div className="canvas">
      <div className="canvas__flow">
        {items.map((item, i) => {
          const node = nodeFor(item)
          const isLast = i === items.length - 1
          return (
            <div key={item.id} className={`canvas__row canvas__row--${node.status}`}>
              <div className="canvas__rail">
                <div className={`canvas__dot canvas__dot--${node.status}`} />
                {!isLast && <div className="canvas__line" />}
              </div>
              <div className={`canvas__node canvas__node--${node.kind}`}>
                <div className="canvas__node-head">
                  <span className="canvas__node-label">{node.label}</span>
                  {node.status === 'active' && running && <span className="canvas__pulse" />}
                </div>
                {node.sub && <div className="canvas__node-sub">{node.sub}</div>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
