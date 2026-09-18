import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import katex from 'katex'
import mermaid from 'mermaid'
import 'katex/dist/katex.min.css'
import { fetchGraph, type GraphEdge, type GraphNode } from './graphApi'

// Mermaid needs literal hex (it renders inline SVG styles at init time, not
// through the page's CSS) — keep these in sync with the swatch values in
// index.css by hand: swatch-1 #b7d3ba, swatch-3 #386641, swatch-4 #6b9c73.
mermaid.initialize({
  startOnLoad: false,
  theme: 'base',
  themeVariables: {
    primaryColor: '#b7d3ba',
    primaryTextColor: '#386641',
    primaryBorderColor: '#386641',
    lineColor: '#6b9c73',
    fontFamily: "'Plus Jakarta Sans', sans-serif",
    fontSize: '13px',
  },
})

// Mermaid node ids must be plain identifiers, and labels can't contain
// unescaped quotes/brackets/parens — our graph.py already emits ids like
// "n1", but text is free-form agent output (full sentences with commas,
// parens, colons, em-dashes), so sanitize defensively. Both node labels
// ["..."] and edge labels |"..."| must be quoted — an unquoted edge label
// (the old `|text|` form) breaks on the first comma/paren inside it, which
// is exactly what real agent-written labels contain.
function escapeLabel(s: string): string {
  return s
    .replace(/"/g, "'")
    .replace(/[\n\r]/g, ' ')
    .replace(/[[\]{}|#]/g, '')
    .slice(0, 70)
}

function buildDiagram(nodes: GraphNode[], edges: GraphEdge[]): string {
  const lines = ['flowchart TD']
  for (const n of nodes) {
    // ProofSteps get a diamond so they read as "derivation step", not a claim.
    const label = escapeLabel(n.text)
    lines.push(n.kind === 'proofstep' ? `  ${n.id}{"${label}"}` : `  ${n.id}["${label}"]`)
  }
  for (const e of edges) {
    const label = e.label ? `|"${escapeLabel(e.label)}"|` : ''
    lines.push(`  ${e.from} -->${label} ${e.to}`)
  }
  return lines.join('\n')
}

function MathBlock({ tex }: { tex: string }) {
  const html = useMemo(() => {
    try {
      return katex.renderToString(tex, { throwOnError: false, displayMode: true })
    } catch {
      return tex
    }
  }, [tex])
  // eslint-disable-next-line react/no-danger -- KaTeX's own renderToString output, not user HTML
  return <div className="graph-view__detail-math" dangerouslySetInnerHTML={{ __html: html }} />
}

export default function GraphView() {
  const { data } = useQuery({ queryKey: ['graph'], queryFn: fetchGraph, refetchInterval: 3000 })
  const nodes = data?.nodes ?? []
  const edges = data?.edges ?? []
  const containerRef = useRef<HTMLDivElement>(null)
  const [renderError, setRenderError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  const diagram = useMemo(() => buildDiagram(nodes, edges), [nodes, edges])

  useEffect(() => {
    if (nodes.length === 0) {
      if (containerRef.current) containerRef.current.innerHTML = ''
      return
    }
    let active = true
    mermaid
      .render(`graph-${crypto.randomUUID()}`, diagram)
      .then(({ svg }) => {
        if (active && containerRef.current) {
          containerRef.current.innerHTML = svg
          setRenderError(null)
        }
      })
      .catch((e) => {
        if (active) setRenderError(e instanceof Error ? e.message : String(e))
      })
    return () => {
      active = false
    }
  }, [diagram, nodes.length])

  const selectedNode = nodes.find((n) => n.id === selected)

  return (
    <div className="graph-view">
      <div className="graph-view__canvas">
        {nodes.length === 0 ? (
          <div className="graph-view__empty">
            No graph yet — as the agent researches, it adds nodes and causal links here, live.
          </div>
        ) : (
          <div ref={containerRef} className="graph-view__svg" />
        )}
        {renderError && <div className="graph-view__error">{renderError}</div>}
      </div>

      <aside className="graph-view__nodes">
        <div className="graph-view__nodes-head">Nodes ({nodes.length})</div>
        <div className="graph-view__nodes-list">
          {nodes.map((n) => (
            <button
              key={n.id}
              className={`graph-view__node-row ${selected === n.id ? 'graph-view__node-row--active' : ''}`}
              onClick={() => setSelected(n.id === selected ? null : n.id)}
            >
              <span className="graph-view__node-id">
                {n.id}
                {n.claim_type && ` · ${n.claim_type}`}
              </span>
              <span className="graph-view__node-text">{n.text}</span>
            </button>
          ))}
        </div>

        {selectedNode && (
          <div className="graph-view__detail">
            {(selectedNode.claim_type || selectedNode.status) && (
              <div className="graph-view__detail-meta">
                {selectedNode.claim_type}
                {selectedNode.claim_type && selectedNode.status && ' · '}
                {selectedNode.status}
              </div>
            )}
            <div className="graph-view__detail-text">{selectedNode.text}</div>
            {selectedNode.math && <MathBlock tex={selectedNode.math} />}
            {selectedNode.code && (
              <pre className="graph-view__detail-code">
                <code>{selectedNode.code}</code>
              </pre>
            )}
          </div>
        )}
      </aside>
    </div>
  )
}
