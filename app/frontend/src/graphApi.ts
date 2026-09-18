import { apiUrl } from './api'

export type GraphNode = {
  id: string
  kind?: 'claim' | 'inference'
  claim_type?: string
  status?: string
  scope?: 'local' | 'global'
  text: string
  math?: string
  code?: string
  code_lang?: string
}

export type GraphEdge = {
  from: string
  to: string
  label?: string
}

export type GraphData = { nodes: GraphNode[]; edges: GraphEdge[] }

export async function fetchGraph(): Promise<GraphData> {
  const res = await fetch(apiUrl('/api/graph'))
  if (!res.ok) throw new Error(`graph fetch failed: ${res.status}`)
  return res.json()
}
