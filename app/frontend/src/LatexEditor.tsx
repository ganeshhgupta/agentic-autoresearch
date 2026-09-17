import { useCallback, useEffect, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { StreamLanguage } from '@codemirror/language'
import { stex } from '@codemirror/legacy-modes/mode/stex'
import { apiUrl } from './api'

const stexLang = StreamLanguage.define(stex)

const DEFAULT_TEX = `\\documentclass{article}
\\begin{document}
Hello, world!
\\end{document}
`

export default function LatexEditor() {
  const [files, setFiles] = useState<string[]>([])
  const [name, setName] = useState<string | null>(null)
  const [content, setContent] = useState(DEFAULT_TEX)
  const [dirty, setDirty] = useState(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [log, setLog] = useState<string | null>(null)
  const [compiling, setCompiling] = useState(false)
  const pdfUrlRef = useRef<string | null>(null)

  const refreshFiles = useCallback(async () => {
    const res = await fetch(apiUrl('/api/latex/files'))
    const list: string[] = await res.json()
    setFiles(list)
    return list
  }, [])

  const openFile = useCallback(async (fname: string) => {
    const res = await fetch(apiUrl(`/api/latex/file/${encodeURIComponent(fname)}`))
    if (!res.ok) return
    const data = await res.json()
    setName(fname)
    setContent(data.content)
    setDirty(false)
    setLog(null)
  }, [])

  useEffect(() => {
    refreshFiles().then((list) => {
      if (list.length > 0) openFile(list[0])
    })
  }, [refreshFiles, openFile])

  useEffect(() => {
    return () => {
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
    }
  }, [])

  function newFile() {
    const input = window.prompt('New file name (e.g. draft.tex)', 'draft.tex')
    if (!input) return
    const finalName = input.endsWith('.tex') ? input : `${input}.tex`
    setName(finalName)
    setContent(DEFAULT_TEX)
    setDirty(true)
    setLog(null)
  }

  async function save() {
    if (!name) return
    await fetch(apiUrl('/api/latex/file'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, content }),
    })
    setDirty(false)
    await refreshFiles()
  }

  async function compile() {
    if (!name) return
    if (dirty) await save()
    setCompiling(true)
    setLog(null)
    try {
      const res = await fetch(apiUrl(`/api/latex/compile/${encodeURIComponent(name)}`), { method: 'POST' })
      if (!res.ok) {
        const detail = await res.json().catch(() => null)
        setLog(detail?.detail ?? `compile failed (${res.status})`)
        return
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
      pdfUrlRef.current = url
      setPdfUrl(url)
    } finally {
      setCompiling(false)
    }
  }

  return (
    <div className="latex">
      <div className="latex__files">
        {files.map((f) => (
          <button
            key={f}
            className={`latex__file ${f === name ? 'latex__file--active' : ''}`}
            onClick={() => openFile(f)}
          >
            {f}
          </button>
        ))}
        <button className="latex__file latex__file--new" onClick={newFile}>
          + New
        </button>
      </div>

      <div className="latex__panes">
        <div className="latex__pane latex__pane--edit">
          <div className="latex__pane-head">
            <span>
              {name ?? 'no file open'}
              {dirty ? ' *' : ''}
            </span>
            <div className="latex__actions">
              <button onClick={save} disabled={!name || !dirty}>
                Save
              </button>
              <button onClick={compile} disabled={!name || compiling}>
                {compiling ? 'Compiling…' : 'Compile'}
              </button>
            </div>
          </div>
          <div className="latex__editor">
            <CodeMirror
              value={content}
              height="100%"
              theme="dark"
              extensions={[stexLang]}
              onChange={(value) => {
                setContent(value)
                setDirty(true)
              }}
            />
          </div>
          {log && <pre className="latex__log">{log}</pre>}
        </div>

        <div className="latex__pane latex__pane--preview">
          {pdfUrl ? (
            <iframe title="PDF preview" src={pdfUrl} />
          ) : (
            <div className="latex__preview-empty">Compile to see a preview</div>
          )}
        </div>
      </div>
    </div>
  )
}
