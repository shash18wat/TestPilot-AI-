import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from 'react'

const API = (import.meta as any).env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000'
type Operation = { id: string; operation_id: string; method: string; path: string; summary: string; parameters: { name: string; in: string; required: boolean; type: string; description: string }[]; request_schema: Record<string, any> | null; expected_status: number | null }
type Spec = { id: number; name: string; created_at: string; operation_count?: number; operations?: Operation[] }
type Run = { id: number; spec_id: number; operation_id: string; operation_label: string; method: string; safe_path: string; status_code: number | null; passed: boolean; elapsed_ms: number | null; expected_status: number | null; json_valid: boolean | null; summary: string; created_at: string }
type Health = { status: string; ai_configured: boolean; auth_configured: boolean }
type Session = { loaded: boolean; configured: boolean; authenticated: boolean; email?: string }

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...options, credentials: 'include', headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) } })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`)
  return data as T
}

function Icon({ name }: { name: string }) {
  const paths: Record<string, string> = {
    grid: 'M4 4h6v6H4z M14 4h6v6h-6z M4 14h6v6H4z M14 14h6v6h-6z',
    box: 'M12 3 3.5 7.5 12 12l8.5-4.5L12 3Z M3.5 12.5 12 17l8.5-4.5 M3.5 17 12 21l8.5-4',
    clock: 'M12 8v4l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
    settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-1.8 1.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5v.2h-2.6v-.2a1.7 1.7 0 0 0-1-1.5 1.7 1.7 0 0 0-1.9.3l-.1.1-1.8-1.8.1-.1A1.7 1.7 0 0 0 8 15a1.7 1.7 0 0 0-1.5-1H6.3v-2.6h.2a1.7 1.7 0 0 0 1.5-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1 1.8-1.8.1.1a1.7 1.7 0 0 0 1.9.3 1.7 1.7 0 0 0 1-1.5v-.2H15v.2a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1 1.8 1.8-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.5 1h.2V14h-.2a1.7 1.7 0 0 0-1.5 1Z',
    upload: 'M12 16V4 M7 9l5-5 5 5 M4 16v4h16v-4',
    play: 'M8 5v14l11-7z',
    check: 'm5 12 4 4L19 6',
    spark: 'm12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z M19 16v5 M16.5 18.5h5',
    plus: 'M12 5v14 M5 12h14',
    arrow: 'M5 12h14 M13 6l6 6-6 6',
    shield: 'M12 22s8-4 8-11V5l-8-3-8 3v6c0 7 8 11 8 11Z M9 12l2 2 4-4',
  }
  return <svg className="icon" viewBox="0 0 24 24" aria-hidden="true"><path d={paths[name] || paths.grid} /></svg>
}

function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [session, setSession] = useState<Session>({ loaded: false, configured: false, authenticated: false })
  const [allowedHosts, setAllowedHosts] = useState<string[]>([])
  const [specs, setSpecs] = useState<Spec[]>([])
  const [selectedSpecId, setSelectedSpecId] = useState<number | null>(null)
  const [collection, setCollection] = useState<Spec | null>(null)
  const [runs, setRuns] = useState<Run[]>([])
  const [selectedOperation, setSelectedOperation] = useState<Operation | null>(null)
  const [tab, setTab] = useState<'overview' | 'collections' | 'history' | 'settings'>('overview')
  const [targetBaseUrl, setTargetBaseUrl] = useState('')
  const [bodyText, setBodyText] = useState('')
  const [headersText, setHeadersText] = useState('{}')
  const [pathParamsText, setPathParamsText] = useState('{}')
  const [queryParamsText, setQueryParamsText] = useState('{}')
  const [expectedStatus, setExpectedStatus] = useState('')
  const [expectJson, setExpectJson] = useState(true)
  const [loading, setLoading] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [specName, setSpecName] = useState('')
  const [specContent, setSpecContent] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [aiNote, setAiNote] = useState('')
  const [explanation, setExplanation] = useState<Record<number, string>>({})

  const refresh = useCallback(async () => {
    try {
      const login = await api<Omit<Session, 'loaded'>>('/api/auth/session')
      setSession({ ...login, loaded: true })
      const h = await api<Health>('/api/health')
      setHealth(h)
      if (!login.authenticated) { setSpecs([]); setRuns([]); setAllowedHosts([]); return }
      const [s, r, workspaceSettings] = await Promise.all([api<Spec[]>('/api/specs'), api<Run[]>('/api/runs?limit=30'), api<{ allowed_hosts: string[] }>('/api/settings')])
      setSpecs(s); setRuns(r); setAllowedHosts(workspaceSettings.allowed_hosts)
      setSelectedSpecId(current => current && s.some(item => item.id === current) ? current : s[0]?.id ?? null)
    } catch (e) { setSession(current => ({ ...current, loaded: true })); setError((e as Error).message) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])
  useEffect(() => {
    if (!selectedSpecId) { setCollection(null); setSelectedOperation(null); return }
    api<Spec>(`/api/specs/${selectedSpecId}`).then(spec => {
      setCollection(spec)
      setSelectedOperation(current => current && spec.operations?.some(op => op.id === current.id) ? current : spec.operations?.[0] || null)
    }).catch(e => setError((e as Error).message))
  }, [selectedSpecId])
  const scopedRuns = useMemo(() => runs.filter(run => !selectedSpecId || run.spec_id === selectedSpecId), [runs, selectedSpecId])
  const passedCount = scopedRuns.filter(run => run.passed).length
  const passRate = scopedRuns.length ? Math.round(passedCount / scopedRuns.length * 100) : 0

  function openOperation(operation: Operation) {
    setSelectedOperation(operation)
    setExpectedStatus(operation.expected_status ? String(operation.expected_status) : '')
    setPathParamsText(JSON.stringify(Object.fromEntries(operation.parameters.filter(p => p.in === 'path').map(p => [p.name, ''])), null, 2))
    setQueryParamsText(JSON.stringify(Object.fromEntries(operation.parameters.filter(p => p.in === 'query').map(p => [p.name, ''])), null, 2))
    setBodyText(operation.request_schema ? JSON.stringify(exampleBody(operation.request_schema), null, 2) : '')
    setNotice('')
  }
  async function importSpec(event?: FormEvent) {
    event?.preventDefault(); setError(''); setNotice('')
    try {
      if (!specName.trim() || !specContent.trim()) throw new Error('Add a collection name and an OpenAPI YAML or JSON document.')
      setLoading(true)
      const result = await api<{ id: number; operations: Operation[] }>('/api/specs/import', { method: 'POST', body: JSON.stringify({ name: specName, content: specContent }) })
      setSpecName(''); setSpecContent(''); setImportOpen(false)
      await refresh(); setSelectedSpecId(result.id); setTab('collections'); setNotice(`Imported ${result.operations.length} operations.`)
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  async function loadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return
    setSpecName(file.name.replace(/\.(ya?ml|json)$/i, '')); setSpecContent(await file.text()); event.target.value = ''
  }
  async function executeTest() {
    if (!collection || !selectedOperation) return
    setError(''); setNotice('')
    try {
      setLoading(true)
      const body = bodyText.trim() ? JSON.parse(bodyText) : undefined
      const result = await api<Run>('/api/runs', { method: 'POST', body: JSON.stringify({
        spec_id: collection.id, operation_id: selectedOperation.id, target_base_url: targetBaseUrl,
        path_params: JSON.parse(pathParamsText || '{}'), query_params: JSON.parse(queryParamsText || '{}'),
        headers: JSON.parse(headersText || '{}'), body, expected_status: expectedStatus ? Number(expectedStatus) : null, expect_json: expectJson,
      }) })
      setNotice(result.summary); await refresh()
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  async function getSuggestions() {
    if (!collection) return
    setLoading(true); setError(''); setAiNote('')
    try {
      const result = await api<{ suggestions: any[]; note?: string }>(`/api/ai/specs/${collection.id}/suggestions`, { method: 'POST' })
      setSuggestions(result.suggestions); setAiNote(result.note || '')
    } catch (e) { setError((e as Error).message) } finally { setLoading(false) }
  }
  async function explain(runId: number) {
    setExplanation(current => ({ ...current, [runId]: 'Thinking through the result…' }))
    try {
      const result = await api<{ explanation: string }>(`/api/ai/runs/${runId}/explanation`, { method: 'POST' })
      setExplanation(current => ({ ...current, [runId]: result.explanation }))
    } catch (e) { setExplanation(current => ({ ...current, [runId]: (e as Error).message })) }
  }

  async function logout() {
    try { await fetch(`${API}/api/auth/logout`, { method: 'POST', credentials: 'include' }) } finally {
      setSession(current => ({ ...current, authenticated: false, email: undefined }))
      setSpecs([]); setRuns([]); setAllowedHosts([]); setCollection(null); setSelectedSpecId(null)
    }
  }

  const authError = new URLSearchParams(window.location.search).get('auth_error')
  const loginMessage = authError === 'account'
    ? 'This workspace is limited to tiwarishashwat36@gmail.com. Choose that Google account to continue.'
    : authError === 'setup'
      ? 'Google sign-in needs to be configured in the backend .env file.'
      : authError === 'sign_in' ? 'Google sign-in could not be completed. Please try again.' : ''
  if (!session.loaded) return <div className="login-shell"><div className="login-card"><div className="brand-mark"><span>TP</span></div><h1>Opening your workspace…</h1><p>Checking sign-in status.</p></div></div>
  if (!session.authenticated) return <div className="login-shell"><div className="login-card"><div className="brand-mark"><span>TP</span></div><div className="eyebrow login-eyebrow"><span className="eyebrow-line"/>TESTPILOT AI</div><h1>Your API testing workspace</h1><p>Sign in with the permitted Google account to access collections and test history.</p><div className="login-account"><span className="login-avatar">{session.configured ? 'G' : '!'}</span><span><b>{session.configured ? 'Google account access' : 'Google sign-in setup required'}</b><small>{session.configured ? 'tiwarishashwat36@gmail.com' : 'Add OAuth credentials and a session secret to backend .env'}</small></span></div>{loginMessage && <div className="login-error" role="alert">{loginMessage}</div>}{session.configured ? <button className="google-button" onClick={() => window.location.assign(`${API}/api/auth/google/start`)}><span className="google-g">G</span>Continue with Google</button> : <button className="google-button disabled" disabled>Sign-in is not configured</button>}<small className="login-footnote">Only the configured owner account can access this local workspace.</small>{error && <div className="login-error" role="alert">{error}<button onClick={() => { setError(''); void refresh() }}>Retry</button></div>}</div></div>

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span>TP</span></div><div><strong>TestPilot</strong><small>AI API WORKSPACE</small></div></div>
      <div className="workspace-label">WORKSPACE <button className="tiny-plus" title="Add collection" onClick={() => setImportOpen(true)}><Icon name="plus" /></button></div>
      <nav className="nav-list">
        <NavButton active={tab === 'overview'} icon="grid" label="Overview" onClick={() => setTab('overview')} />
        <NavButton active={tab === 'collections'} icon="box" label="Collections" count={specs.length} onClick={() => setTab('collections')} />
        <NavButton active={tab === 'history'} icon="clock" label="Run history" onClick={() => setTab('history')} />
      </nav>
      <div className="side-section-title">YOUR COLLECTIONS</div>
      <div className="collection-nav">
        {specs.map(spec => <button key={spec.id} className={selectedSpecId === spec.id ? 'collection-link selected' : 'collection-link'} onClick={() => { setSelectedSpecId(spec.id); setTab('collections') }}><span className="collection-dot">{spec.name.charAt(0).toUpperCase()}</span><span className="truncate">{spec.name}</span><span className="endpoint-count">{spec.operation_count}</span></button>)}
        {!specs.length && <p className="side-empty">Import an OpenAPI file to get started.</p>}
      </div>
      <div className="sidebar-bottom">
        <div className="security-card"><div className="security-icon"><Icon name="shield" /></div><div><strong>Target protection</strong><small>{allowedHosts.length ? `${allowedHosts.length} host${allowedHosts.length === 1 ? '' : 's'} permitted` : 'Outbound testing locked'}</small></div><span className={allowedHosts.length ? 'status-dot good' : 'status-dot'} /></div>
        <button className="nav-item settings-nav" onClick={() => setTab('settings')}><Icon name="settings" />Settings</button>
        <div className="profile"><div className="avatar">{session.email?.slice(0, 1).toUpperCase() || 'TP'}</div><div><strong>{session.email || 'Google account'}</strong><small>Signed in</small></div><button className="logout-button" onClick={() => void logout()} title="Sign out">↗</button></div>
      </div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumbs"><span>Workspace</span><span className="crumb-slash">/</span><strong>{tab === 'history' ? 'Run history' : tab === 'settings' ? 'Settings' : tab === 'collections' ? 'Collections' : 'Overview'}</strong></div><div className="top-actions"><div className="api-state"><span className={health ? 'status-dot good' : 'status-dot'} />{health ? 'API connected' : 'Connecting…'}</div><div className="vertical-line"/><button className="ai-chip"><Icon name="spark" />{health?.ai_configured ? 'Gemini enabled' : 'AI fallback active'}</button><button className="top-logout" onClick={() => void logout()}>Sign out</button></div></header>
      <div className="page-content">
        {tab === 'overview' && <>
          <section className="welcome-row"><div><div className="eyebrow"><span className="eyebrow-line"/>API QUALITY, ON AUTOPILOT</div><h1>Good testing starts<br/>with a <span>clear signal.</span></h1><p className="welcome-copy">Bring your API contracts into one workspace. Run checks, track results, and use AI to find the next edge case.</p><div className="hero-actions"><button className="primary-button" onClick={() => setImportOpen(true)}><Icon name="upload"/>Import OpenAPI spec</button><button className="quiet-button" onClick={() => setTab('collections')}>Explore collections <Icon name="arrow"/></button></div></div><HeroArt/></section>
          <section className="stats-grid"><StatCard label="COLLECTIONS" value={String(specs.length).padStart(2, '0')} foot="OpenAPI workspaces" accent="green" icon="box"/><StatCard label="ENDPOINTS" value={String(specs.reduce((n, s) => n + (s.operation_count || 0), 0)).padStart(2, '0')} foot="Ready to run" accent="blue" icon="grid"/><StatCard label="TEST RUNS" value={String(scopedRuns.length).padStart(2, '0')} foot="Latest collection" accent="violet" icon="play"/><StatCard label="PASS RATE" value={`${passRate}%`} foot={scopedRuns.length ? `${passedCount} checks passed` : 'No runs yet'} accent="amber" icon="check"/></section>
          <div className="section-heading"><div><h2>Workspace activity</h2><p>Recent API test runs across your collections.</p></div><button className="text-link" onClick={() => setTab('history')}>View all <Icon name="arrow"/></button></div><RunTable runs={runs.slice(0, 5)} onExplain={explain} explanation={explanation}/>
        </>}

        {tab === 'collections' && <>
          <div className="page-title-row"><div><div className="eyebrow"><span className="eyebrow-line"/>API CONTRACTS</div><h1>Collections</h1><p className="welcome-copy">Choose an operation, configure a request, and run it against an explicitly permitted target.</p></div><button className="primary-button" onClick={() => setImportOpen(true)}><Icon name="plus"/>Import spec</button></div>
          {!specs.length ? <EmptyState onImport={() => setImportOpen(true)}/> : <div className="collection-workspace">
            <section className="panel operations-panel"><div className="panel-heading"><div><span className="eyebrow mini">COLLECTION</span><h2>{collection?.name || 'Loading…'}</h2></div><span className="counter-pill">{collection?.operations?.length || 0} operations</span></div><div className="op-list">{collection?.operations?.map(operation => <button key={operation.id} className={`operation-row ${selectedOperation?.id === operation.id ? 'op-selected' : ''}`} onClick={() => openOperation(operation)}><MethodBadge method={operation.method}/><span className="op-copy"><strong>{operation.path}</strong><small>{operation.summary}</small></span><span className="op-chevron">›</span></button>)}</div></section>
            <section className="panel request-panel"><div className="request-title"><div><span className="eyebrow mini">REQUEST BUILDER</span><h2>{selectedOperation ? selectedOperation.summary : 'Select an operation'}</h2></div>{selectedOperation && <MethodBadge method={selectedOperation.method}/>}</div>
              {selectedOperation && <>
                <div className="route-line"><span className="route-method">{selectedOperation.method}</span><span>{selectedOperation.path}</span></div>
                <label className="field-label">TEST TARGET BASE URL <span>Must match a permitted hostname</span><input className="text-input" value={targetBaseUrl} onChange={e => setTargetBaseUrl(e.target.value)} placeholder="https://api.your-domain.com"/></label>
                <div className="form-two"><label className="field-label">EXPECTED STATUS<input className="text-input compact-input" value={expectedStatus} onChange={e => setExpectedStatus(e.target.value)} placeholder="e.g. 200" inputMode="numeric"/></label><label className="toggle-field"><input type="checkbox" checked={expectJson} onChange={e => setExpectJson(e.target.checked)}/><span><b>Validate JSON response</b><small>Check JSON content and syntax</small></span></label></div>
                {selectedOperation.parameters.some(p => p.in === 'path') && <JsonField label="PATH PARAMETERS" value={pathParamsText} onChange={setPathParamsText}/>}
                {selectedOperation.parameters.some(p => p.in === 'query') && <JsonField label="QUERY PARAMETERS" value={queryParamsText} onChange={setQueryParamsText}/>}
                {['POST','PUT','PATCH'].includes(selectedOperation.method) && <JsonField label="JSON BODY" value={bodyText} onChange={setBodyText}/>}
                <JsonField label="REQUEST HEADERS" value={headersText} onChange={setHeadersText} helper="Credentials stay in memory and are never saved to run history."/>
                <div className="request-footer"><span><Icon name="shield"/>Target allowlist enforced</span><button className="primary-button run-button" disabled={loading || !targetBaseUrl} onClick={() => void executeTest()}><Icon name="play"/>{loading ? 'Running…' : 'Run test'}</button></div>
              </>}
            </section>
            <section className="panel ai-panel"><div className="ai-panel-head"><div className="ai-orb"><Icon name="spark"/></div><div><h2>AI test suggestions</h2><p>{health?.ai_configured ? 'Powered by Gemini' : 'Built-in suggestions · Gemini optional'}</p></div><button className="icon-button" title="Generate suggestions" onClick={() => void getSuggestions()} disabled={loading}><Icon name="arrow"/></button></div><p className="ai-description">Find useful happy paths and edge cases based on your OpenAPI schema.</p><button className="suggest-button" onClick={() => void getSuggestions()} disabled={loading}><Icon name="spark"/>{suggestions.length ? 'Refresh suggestions' : 'Generate suggestions'}</button>{aiNote && <div className="ai-note">{aiNote}</div>}{suggestions.map((suggestion, index) => <button key={index} className="suggestion-card" onClick={() => { const match = collection?.operations?.find(op => op.path === suggestion.path && op.method === suggestion.method); if (match) { openOperation(match); setExpectedStatus(String(suggestion.expected_status || '')); if (suggestion.body) setBodyText(JSON.stringify(suggestion.body, null, 2)) } }}><span className="suggestion-index">0{index + 1}</span><span><b>{suggestion.title}</b><small>{suggestion.rationale}</small></span><span className="suggestion-arrow">↗</span></button>)}</section>
          </div>}
        </>}

        {tab === 'history' && <><div className="page-title-row"><div><div className="eyebrow"><span className="eyebrow-line"/>EXECUTION LOG</div><h1>Run history</h1><p className="welcome-copy">A private record of test outcomes. Request and response bodies are never retained.</p></div><button className="secondary-button" onClick={() => void refresh()}><Icon name="clock"/>Refresh</button></div><RunTable runs={runs} onExplain={explain} explanation={explanation}/></>}

        {tab === 'settings' && <><div className="page-title-row"><div><div className="eyebrow"><span className="eyebrow-line"/>WORKSPACE CONFIGURATION</div><h1>Settings</h1><p className="welcome-copy">Manage local security posture and optional AI availability.</p></div></div><div className="settings-grid"><div className="panel settings-card"><div className="settings-card-icon"><Icon name="shield"/></div><h2>Outbound target allowlist</h2><p>TestPilot only calls exact public hostnames configured by your backend. Redirects, private IPs, and nonstandard ports are blocked.</p><div className="host-list">{allowedHosts.length ? allowedHosts.map(host => <span className="host-tag" key={host}>{host}</span>) : <span className="empty-hosts">No hosts permitted</span>}</div><small>Edit <code>TESTPILOT_ALLOWED_HOSTS</code> in your backend <code>.env</code> and restart the API.</small></div><div className="panel settings-card"><div className="settings-card-icon purple"><Icon name="spark"/></div><h2>AI assistance</h2><p>{health?.ai_configured ? 'Gemini is configured on the backend. Your API key stays server-side.' : 'Gemini is optional. Schema-based suggestions and basic failure explanations work without a key.'}</p><div className="setting-status"><span className={health?.ai_configured ? 'status-dot good' : 'status-dot'}/>{health?.ai_configured ? 'Gemini ready' : 'Using built-in fallback'}</div><small>Set <code>GEMINI_API_KEY</code> on the backend to enable Gemini.</small></div></div></>}
        {error && <div className="toast error-toast" role="alert"><span>!</span>{error}<button onClick={() => setError('')}>×</button></div>}
        {notice && <div className="toast success-toast" role="status"><span>✓</span>{notice}<button onClick={() => setNotice('')}>×</button></div>}
      </div>
    </main>
    {importOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) setImportOpen(false) }}><form className="modal" onSubmit={e => void importSpec(e)}><div className="modal-head"><div><div className="eyebrow"><span className="eyebrow-line"/>NEW COLLECTION</div><h2>Import an OpenAPI spec</h2><p>Load a YAML or JSON contract to build your operation list.</p></div><button className="modal-close" type="button" onClick={() => setImportOpen(false)}>×</button></div><label className="field-label">COLLECTION NAME<input className="text-input" value={specName} onChange={e => setSpecName(e.target.value)} placeholder="Payments API"/></label><label className="field-label spec-upload">SPEC DOCUMENT<input type="file" accept=".yaml,.yml,.json,application/json,text/yaml" onChange={e => void loadFile(e)}/><span><Icon name="upload"/>Choose a file or paste the document below</span></label><textarea className="code-input spec-input" value={specContent} onChange={e => setSpecContent(e.target.value)} placeholder={'openapi: 3.0.3\ninfo:\n  title: Example API\n  version: 1.0.0\npaths:\n  /health:\n    get:\n      summary: Health check\n      responses:\n        "200":\n          description: OK'} rows={12}/><div className="modal-footer"><span>OpenAPI 3.x · YAML or JSON · max 1 MB</span><button className="primary-button" type="submit" disabled={loading}>{loading ? 'Importing…' : 'Import collection'}<Icon name="arrow"/></button></div></form></div>}
  </div>
}

function NavButton({ active, icon, label, count, onClick }: { active: boolean; icon: string; label: string; count?: number; onClick: () => void }) {
  return <button className={active ? 'nav-item active' : 'nav-item'} title={label} aria-current={active ? 'page' : undefined} onClick={onClick}><Icon name={icon}/>{label}{count !== undefined && <span className="nav-count">{count}</span>}</button>
}
function exampleBody(schema: Record<string, any>): any {
  if (schema.example !== undefined) return schema.example
  if (schema.type === 'object' || schema.properties) { const props = schema.properties || {}; const keys = schema.required?.length ? schema.required : Object.keys(props).slice(0, 4); return Object.fromEntries(keys.slice(0, 8).map((key: string) => [key, exampleBody(props[key] || {})])) }
  if (schema.type === 'array') return [exampleBody(schema.items || {})]
  if (schema.type === 'string') return schema.enum?.[0] || 'example'
  if (schema.type === 'integer' || schema.type === 'number') return schema.minimum ?? 1
  if (schema.type === 'boolean') return true
  return null
}
function MethodBadge({ method }: { method: string }) { return <span className={`method-badge method-${method.toLowerCase()}`}>{method}</span> }
function StatCard({ label, value, foot, accent, icon }: { label: string; value: string; foot: string; accent: string; icon: string }) {
  return <div className="stat-card"><div className={`stat-icon ${accent}`}><Icon name={icon}/></div><div className="stat-label">{label}</div><div className="stat-value">{value}</div><div className="stat-foot"><span className={`stat-marker ${accent}`}/>{foot}</div><div className={`stat-decoration ${accent}`}/></div>
}
function HeroArt() {
  return <div className="hero-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="orbit-core"><span className="core-cross">+</span><span className="core-star">✳</span></div><div className="float-card float-top"><span className="tiny-check"><Icon name="check"/></span><span><b>Contract verified</b><small>schema · response · latency</small></span></div><div className="float-card float-bottom"><span className="pulse-dot"/><span><b>Test suite ready</b><small>AI-assisted suggestions</small></span></div><div className="sparkle sparkle-a">✦</div><div className="sparkle sparkle-b">·</div></div>
}
function JsonField({ label, value, onChange, helper }: { label: string; value: string; onChange: (value: string) => void; helper?: string }) {
  return <label className="field-label json-label">{label}{helper && <span>{helper}</span>}<textarea className="code-input" value={value} onChange={e => onChange(e.target.value)} rows={label === 'JSON BODY' ? 6 : 3} spellCheck={false}/></label>
}
function EmptyState({ onImport }: { onImport: () => void }) {
  return <div className="panel empty-state"><div className="empty-illustration"><div className="empty-icon"><Icon name="box"/></div><span className="empty-orbit orbit-a"/><span className="empty-orbit orbit-b"/></div><h2>Your first collection is one import away</h2><p>Import an OpenAPI document to see your endpoints, generate starter tests, and begin building a reliable signal.</p><button className="primary-button" onClick={onImport}><Icon name="upload"/>Import OpenAPI spec</button></div>
}
function RunTable({ runs, onExplain, explanation }: { runs: Run[]; onExplain: (id: number) => void; explanation: Record<number, string> }) {
  if (!runs.length) return <div className="panel empty-table"><div className="empty-icon small"><Icon name="clock"/></div><h3>No test runs yet</h3><p>Run an API check from a collection and the result will appear here.</p></div>
  return <div className="panel table-panel"><div className="table-header"><span>RESULT</span><span>OPERATION</span><span>RESPONSE</span><span>LATENCY</span><span>WHEN</span><span/></div>{runs.map(run => <div className="run-row-wrap" key={run.id}><div className="table-row"><div><span className={run.passed ? 'result-pill passed' : 'result-pill failed'}><span/>{run.passed ? 'Passed' : 'Failed'}</span></div><div className="table-operation"><MethodBadge method={run.method}/><span><strong>{run.safe_path}</strong><small>{run.operation_label}</small></span></div><div className="response-cell">{run.status_code ?? '—'} <small>{run.expected_status ? `expected ${run.expected_status}` : ''}</small></div><div className="latency-cell">{run.elapsed_ms == null ? '—' : `${run.elapsed_ms} ms`}</div><div className="date-cell">{run.created_at ? new Date(run.created_at).toLocaleString() : 'Just now'}</div><div>{!run.passed && <button className="explain-button" onClick={() => void onExplain(run.id)} title="Explain this failure"><Icon name="spark"/></button>}</div></div>{explanation[run.id] && <div className="explanation-row"><Icon name="spark"/><span>{explanation[run.id]}</span></div>}</div>)}</div>
}

export default App
