import { useEffect, useRef, useState, type FormEvent } from 'react'

/* ---------- Types (mirror backend enums.py / store.conversation_detail) ---------- */

type Installment = { n: number; amount_cents: number; due_date: string; status?: string }
type Option = { plan_type: string; label: string; installments: Installment[] }
type ReasonOption = { code: string; label: string }
type Msg = { id: number; role: 'agent' | 'borrower'; text: string; kind: string; payload: any }
type LoanInfo = { loan_id: number; name: string; amount_due_cents: number; due_date: string; status: string }
type Detail = {
  conversation_id: number
  loan: LoanInfo
  status: string
  outcome: string
  ended: boolean
  summary: string
  reason_code: string | null
  payment_choice: string
  verified_at: string | null
  messages: Msg[]
  confirmed_plan: { plan_id: number; plan_type: string; status: string; installments: Installment[] } | null
}
type LoanRow = {
  loan_id: number
  customer_name: string
  phone_last4: string
  amount_due_cents: number
  due_date: string
  status: string
  last_outcome: string | null
  has_confirmed_plan: boolean
  open_conversation_id: number | null
}

type EscalationRow = { conversation_id: number; customer_name: string; amount_due_cents: number; reason: string | null; summary: string; ended_at: string | null }
type PlanRow = { plan_id: number; customer_name: string; plan_type: string; total_cents: number; confirmed_at: string | null; installments: Installment[] }

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const OUTCOMES: Record<string, { label: string; tone: 'neutral' | 'good' | 'warn' | 'stop' }> = {
  in_progress: { label: 'In progress', tone: 'neutral' },
  promise_to_pay: { label: 'Paid in full plan', tone: 'good' },
  payment_plan: { label: 'Payment plan', tone: 'good' },
  extension: { label: 'Extension', tone: 'good' },
  hardship_referral: { label: 'Hardship: team follow-up', tone: 'warn' },
  escalated: { label: 'Handed to team', tone: 'warn' },
  dispute: { label: 'Disputed: paused', tone: 'stop' },
  stop_request: { label: 'Opted out', tone: 'stop' },
  attorney: { label: 'Has attorney', tone: 'stop' },
  wrong_person: { label: 'Wrong person', tone: 'stop' },
}

const ENDED_NOTE: Record<string, string> = {
  dispute: 'The member disputed the debt. Collection is paused until the lender sends written verification (FDCPA §809).',
  stop_request: 'The member asked for no further contact (FDCPA §805(c)).',
  attorney: 'The member is represented by an attorney. Contact the attorney only (FDCPA §805(a)(2)).',
  wrong_person: "This isn't the member. Don't discuss the debt with them (FDCPA §805(b)).",
  escalated: "Handed to the lender's team.",
}

const usd = (cents: number) => `$${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const day = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
const firstName = (name: string) => name.split(' ')[0]

async function req<T>(path: string, method: 'GET' | 'POST', body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = (data as any).detail
    const msg = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
      : detail || `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data as T
}
const get = <T,>(p: string) => req<T>(p, 'GET')
const post = <T,>(p: string, b: unknown) => req<T>(p, 'POST', b)

/* ---------- Icons ---------- */

function Wordmark({ className = '' }: { className?: string }) {
  return (
    <span className={`wordmark ${className}`}>
      <svg viewBox="0 0 48 64" className="wordmark-mark" aria-hidden="true">
        <path d="M11 22a13 13 0 0 1 26 0z" fill="#E0A05A" />
        <path d="M24 22C23 34 19 45 20 56" fill="none" stroke="#5C3A1B" strokeWidth="7" strokeLinecap="round" />
        <path d="M13 24 16 16 20 18 24 12 28 18 32 16 35 24Z" fill="#5C3A1B" />
      </svg>
      <span className="wordmark-text">Clovefi</span>
    </span>
  )
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 12l16-8-6 16-2.5-6.5L4 12Z" fill="currentColor" />
    </svg>
  )
}

function BackIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M15 5l-7 7 7 7" stroke="currentColor" strokeWidth="2.2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/* ---------- Landing ---------- */

const STEPS: [string, string][] = [
  ['Reaches out', 'Richie opens with the debt-collection notice the law requires, and asks when the member can pay.'],
  ['Negotiates in policy', 'The app computes the only arrangements your policy allows — pay in full or split into installments. Richie never makes up amounts or dates.'],
  ['Logs the outcome', 'Every reason, confirmed plan and opt-out is saved as structured data you can act on.'],
]

const FEATURES: [string, string][] = [
  ['Follows the FDCPA', 'No threats, honest amounts, right-party contact — §§805–809 built into every message.'],
  ['Honors opt-outs', "Stops on request or when an attorney is involved, and won't contact them again."],
  ['Pauses on disputes', 'Flags the account and holds collection until written verification is sent.'],
  ['The code builds the plan', 'Installment amounts and dates come from policy math, not the model — nothing out of policy can be offered.'],
  ['One confirmed plan', 'Confirmation is idempotent; retries and double-clicks never create a second plan.'],
  ['Decisions as data', 'Reason codes, plans and installments are stored so staff can follow up.'],
]

function Landing({ lender, onInitiate }: { lender: string; onInitiate: () => void }) {
  return (
    <div className="home">
      <header className="home-nav">
        <div className="home-nav-inner">
          <Wordmark />
          <nav className="home-links">
            <a href="#how">How it works</a>
            <a href="#compliance">Compliance</a>
          </nav>
          <button className="btn-gold sm" onClick={onInitiate}>Initiate collections</button>
        </div>
      </header>

      <section className="hero">
        <div className="hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">AI-powered collections</p>
            <h1>Collections that stay <span className="accent">compliant.</span></h1>
            <p className="lede">
              Clovefi is AI-powered collections — Richie reaches out to members in late-stage collections, offers only the
              arrangements your policy allows, and follows the FDCPA on every message — on behalf of {lender}.
            </p>
            <div className="hero-actions">
              <button className="cta" onClick={onInitiate}>Initiate collections</button>
              <a className="ghost-link" href="#how">See how it works →</a>
            </div>
            <div className="trust-row">
              <span>FDCPA-aware</span>
              <span>Every decision logged</span>
              <span>Opt-outs honored</span>
            </div>
          </div>

          <div className="hero-preview" aria-hidden="true">
            <div className="preview-head">
              <span className="head-avatar">R</span>
              <div className="head-text">
                <strong>Richie</strong>
                <span><i className="online" /> {lender}</span>
              </div>
              <span className="badge good">Payment plan</span>
            </div>
            <div className="preview-body">
              <div className="pv agent">Your payment of $1,000.00 is past due. When can you pay?</div>
              <div className="pv borrower">I can't pay all of it right now.</div>
              <div className="pv agent">No problem — here are a few options that fit.</div>
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="section">
        <h2>How Richie works</h2>
        <div className="steps">
          {STEPS.map(([title, body], i) => (
            <div className="step" key={title}>
              <span className="step-n">{i + 1}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="compliance" className="section tint">
        <h2>Built to stay within the lines</h2>
        <p className="section-sub">Compliance isn't a disclaimer bolted on — it's how Richie is wired.</p>
        <div className="grid">
          {FEATURES.map(([title, body]) => (
            <div className="feature" key={title}>
              <span className="feature-dot" />
              <h3>{title}</h3>
              <p>{body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="cta-band">
        <h2>See Richie handle a conversation.</h2>
        <button className="cta" onClick={onInitiate}>Initiate collections</button>
      </section>

      <footer className="home-foot">
        <Wordmark />
        <span>© {new Date().getFullYear()} Clovefi · On behalf of {lender} · Demo</span>
      </footer>
    </div>
  )
}

/* ---------- Loans due ---------- */

function Staff({ onBack }: { onBack: () => void }) {
  const [tab, setTab] = useState<'escalations' | 'plans'>('escalations')
  const [esc, setEsc] = useState<EscalationRow[] | null>(null)
  const [plans, setPlans] = useState<PlanRow[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    get<{ escalations: EscalationRow[] }>('/api/escalations').then((r) => setEsc(r.escalations)).catch((e) => setError((e as Error).message))
    get<{ plans: PlanRow[] }>('/api/plans').then((r) => setPlans(r.plans)).catch(() => {})
  }, [])

  return (
    <div className="panel wide">
      <button className="back" onClick={onBack}><BackIcon /> Loans due</button>
      <h2>Staff</h2>
      <div className="tabs">
        <button className={`tab ${tab === 'escalations' ? 'active' : ''}`} onClick={() => setTab('escalations')}>Escalations</button>
        <button className={`tab ${tab === 'plans' ? 'active' : ''}`} onClick={() => setTab('plans')}>Confirmed plans</button>
      </div>
      {error && <p className="error">{error}</p>}
      {tab === 'escalations' ? (
        esc === null ? <p className="muted-row">Loading…</p> : esc.length === 0 ? <p className="muted-row">No escalations.</p> : (
          <table className="loans">
            <thead><tr><th>Member</th><th>Amount</th><th>Reason</th><th>Summary</th></tr></thead>
            <tbody>
              {esc.map((e) => (
                <tr key={e.conversation_id}>
                  <td><strong>{e.customer_name}</strong></td>
                  <td>{usd(e.amount_due_cents)}</td>
                  <td><span className="badge warn">{e.reason ?? '—'}</span></td>
                  <td className="wrap">{e.summary || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      ) : (
        plans === null ? <p className="muted-row">Loading…</p> : plans.length === 0 ? <p className="muted-row">No confirmed plans.</p> : (
          <table className="loans">
            <thead><tr><th>Member</th><th>Plan</th><th>Total</th><th>Schedule</th></tr></thead>
            <tbody>
              {plans.map((pl) => (
                <tr key={pl.plan_id}>
                  <td><strong>{pl.customer_name}</strong></td>
                  <td><span className="badge good">{pl.plan_type}</span></td>
                  <td>{usd(pl.total_cents)}</td>
                  <td className="wrap">{pl.installments.map((i) => `${usd(i.amount_cents)} ${day(i.due_date)} (${i.status})`).join(' · ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      )}
    </div>
  )
}

function LoansDue({ onChat, onNew, onStaff, onBack }: { onChat: (d: Detail) => void; onNew: () => void; onStaff: () => void; onBack: () => void }) {
  const [loans, setLoans] = useState<LoanRow[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)

  useEffect(() => {
    get<{ loans: LoanRow[] }>('/api/loans').then((r) => setLoans(r.loans)).catch((e) => setError((e as Error).message))
  }, [])

  async function open(row: LoanRow) {
    setBusy(row.loan_id)
    setError('')
    try {
      const d = row.open_conversation_id
        ? await get<Detail>(`/api/conversations/${row.open_conversation_id}`)
        : await post<Detail>('/api/sessions', { loan_id: row.loan_id })
      onChat(d)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="panel wide">
      <div className="panel-head">
        <button className="back" onClick={onBack}><BackIcon /> Home</button>
        <div className="head-actions">
          <button className="ghost-btn" onClick={onStaff}>Staff</button>
          <button className="btn-gold sm" onClick={onNew}>+ New collection</button>
        </div>
      </div>
      <h2>Loans due</h2>
      <p className="panel-sub">Members with a past-due balance. Open a chat to work an account as the member.</p>
      {error && <p className="error">{error}</p>}
      {loans === null ? (
        <p className="muted-row">Loading…</p>
      ) : loans.length === 0 ? (
        <p className="muted-row">No loans in collections yet. Add one with “New collection”.</p>
      ) : (
        <table className="loans">
          <thead>
            <tr><th>Member</th><th>Amount</th><th>Due</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {loans.map((r) => {
              const badge = OUTCOMES[r.last_outcome ?? 'in_progress'] ?? OUTCOMES.in_progress
              return (
                <tr key={r.loan_id}>
                  <td><strong>{r.customer_name}</strong><span className="sub">••• {r.phone_last4}</span></td>
                  <td>{usd(r.amount_due_cents)}</td>
                  <td>{day(r.due_date)}</td>
                  <td>
                    <span className={`badge ${badge.tone}`}>{r.last_outcome ? badge.label : 'New'}</span>
                    {r.has_confirmed_plan && <span className="badge good">Plan set</span>}
                  </td>
                  <td className="right">
                    <button className="btn-blue sm" disabled={busy === r.loan_id} onClick={() => open(r)}>
                      {busy === r.loan_id ? '…' : r.open_conversation_id ? 'Resume' : 'Chat'}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}

/* ---------- New collection form ---------- */

function NewLoan({ lender, onCreated, onBack }: { lender: string; onCreated: () => void; onBack: () => void }) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await post('/api/loans', { name: name.trim(), phone: phone.trim(), amount_due: amount, due_date: dueDate })
      onCreated()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <button className="back" onClick={onBack}><BackIcon /> Loans due</button>
      <h2>New collection</h2>
      <p className="panel-sub">Add a past-due loan. It appears in the list; open a chat to work it.</p>
      <form className="fields" onSubmit={submit}>
        <label>
          Member name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Jordan Lee" autoComplete="off" required />
        </label>
        <label>
          Phone number
          <input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+1 555 123 4567" autoComplete="off" required />
        </label>
        <div className="row">
          <label>
            Amount due
            <div className="prefix">
              <span>$</span>
              <input type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1000.00" required />
            </div>
          </label>
          <label>
            Due date
            <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
          </label>
        </div>
        {error && <p className="error">{error}</p>}
        <button type="submit" className="btn-blue" disabled={busy}>{busy ? 'Saving…' : 'Add loan'}</button>
        <p className="lender-note">On behalf of {lender}</p>
      </form>
    </div>
  )
}

/* ---------- Chat ---------- */

function Chat({ initial, lender, onExit }: { initial: Detail; lender: string; onExit: () => void }) {
  const [d, setD] = useState<Detail>(initial)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reopen, setReopen] = useState(false)
  const [note, setNote] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [d, busy])

  async function act(fn: () => Promise<Detail>) {
    setBusy(true)
    setError('')
    try { setD(await fn()) } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  function send(e: FormEvent) {
    e.preventDefault()
    const t = draft.trim()
    if (!t || busy || d.ended) return
    setDraft('')
    if (!d.verified_at) act(() => post<Detail>('/api/verify', { conversation_id: d.conversation_id, answer: t }))
    else act(() => post<Detail>('/api/reply', { conversation_id: d.conversation_id, text: t }))
  }
  const pickReason = (code: string) =>
    act(() => post<Detail>('/api/reason', { conversation_id: d.conversation_id, reason_code: code, note: code === 'OTHER' ? note : undefined }))
  const choose = (pt: string) => { setReopen(false); act(() => post<Detail>('/api/choose', { conversation_id: d.conversation_id, plan_type: pt })) }
  const confirm = (planId: number) => act(() => post<Detail>('/api/confirm', { conversation_id: d.conversation_id, plan_id: planId }))

  const hasPlanSummary = d.messages.some((m) => m.kind === 'plan_summary')
  const lastPlanId = [...d.messages].reverse().find((m) => m.kind === 'plan_summary')?.payload?.plan_id
  const reasonActive = !d.reason_code && !d.ended && !busy
  const optionsActive = !d.ended && !d.confirmed_plan && !busy && (reopen || !hasPlanSummary)
  const badge = OUTCOMES[d.outcome] ?? OUTCOMES.in_progress
  const endedNote = d.confirmed_plan ? `Plan confirmed — ${lender} will send payment instructions.` : (ENDED_NOTE[d.outcome] || 'Conversation ended.')

  return (
    <div className="chat-card">
      <header className="chat-head">
        <span className="head-avatar">R</span>
        <div className="head-text">
          <strong>Richie</strong>
          <span><i className="online" /> {lender} · automated assistant</span>
        </div>
        <button className="head-btn text" onClick={onExit}>Loans due</button>
      </header>

      <div className="loan-strip">
        <span><strong>{d.loan.name}</strong> · {usd(d.loan.amount_due_cents)} due {day(d.loan.due_date)}</span>
        <span className={`badge ${badge.tone}`}>{badge.label}</span>
      </div>

      <div className="messages">
        {d.messages.map((m) => {
          if (m.kind === 'reason_picker') {
            return (
              <div key={m.id} className="structured">
                <div className="msg agent"><span className="avatar">R</span><div className="bubble">{m.text}</div></div>
                <div className="chips">
                  {(m.payload?.options as ReasonOption[]).map((o) => (
                    <button key={o.code} className="chip" disabled={!reasonActive} onClick={() => pickReason(o.code)}>{o.label}</button>
                  ))}
                </div>
                {reasonActive && (
                  <input className="note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="If other, add a note (optional)" />
                )}
              </div>
            )
          }
          if (m.kind === 'options_card') {
            return (
              <div key={m.id} className="structured">
                <div className="msg agent"><span className="avatar">R</span><div className="bubble">{m.text}</div></div>
                <div className="options">
                  {(m.payload?.options as Option[]).map((o) => (
                    <button key={o.plan_type} className="option" disabled={!optionsActive} onClick={() => choose(o.plan_type)}>
                      <span className="option-title">{o.label}</span>
                      {o.installments.map((it) => (
                        <span key={it.n} className="option-line">{usd(it.amount_cents)} <em>on {day(it.due_date)}</em></span>
                      ))}
                    </button>
                  ))}
                </div>
              </div>
            )
          }
          if (m.kind === 'plan_summary') {
            const insts: Installment[] = m.payload?.installments ?? []
            const isLast = m.payload?.plan_id === lastPlanId
            return (
              <div key={m.id} className="structured">
                <div className="msg agent"><span className="avatar">R</span><div className="bubble">{m.text}</div></div>
                <div className="plan">
                  {insts.map((it) => (
                    <div key={it.n} className="plan-line"><span>Payment {it.n}</span><span>{usd(it.amount_cents)} · {day(it.due_date)}</span></div>
                  ))}
                  {isLast && !d.ended && (
                    <div className="plan-actions">
                      <button className="btn-blue sm" disabled={busy} onClick={() => confirm(m.payload.plan_id)}>Confirm plan</button>
                      <button className="linklike" disabled={busy} onClick={() => setReopen(true)}>Pick a different option</button>
                    </div>
                  )}
                </div>
              </div>
            )
          }
          return (
            <div key={m.id} className={`msg ${m.role}`}>
              {m.role === 'agent' && <span className="avatar">R</span>}
              <div className="bubble">{m.text}</div>
            </div>
          )
        })}
        {busy && (
          <div className="msg agent"><span className="avatar">R</span><div className="bubble dots"><i /><i /><i /></div></div>
        )}
        <div ref={endRef} />
      </div>

      {error && <p className="error pad">{error}</p>}
      {d.ended ? (
        <div className="ended"><b>Conversation ended.</b> {endedNote}</div>
      ) : (
        <form className="composer" onSubmit={send}>
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={d.verified_at ? `Reply as ${firstName(d.loan.name)}…` : 'Enter the last 4 digits of the phone on file…'}
            autoFocus
          />
          <button type="submit" className="send" disabled={busy || !draft.trim()} aria-label="Send"><SendIcon /></button>
        </form>
      )}
    </div>
  )
}

/* ---------- App ---------- */

type Screen = 'landing' | 'loans' | 'newloan' | 'chat' | 'staff'

export default function App() {
  const [lender, setLender] = useState('State Bank of Elytra')
  const [screen, setScreen] = useState<Screen>('landing')
  const [detail, setDetail] = useState<Detail | null>(null)

  useEffect(() => {
    get<{ lender_name?: string }>('/api/config').then((c) => c.lender_name && setLender(c.lender_name)).catch(() => {})
    document.title = 'Clovefi'
  }, [])

  if (screen === 'landing') {
    return <main className="app"><Landing lender={lender} onInitiate={() => setScreen('loans')} /></main>
  }

  return (
    <main className="app">
      <header className="topbar">
        <button className="topbar-logo" onClick={() => { setScreen('landing'); setDetail(null) }}><Wordmark /></button>
      </header>
      <div className="stage">
        {screen === 'loans' && (
          <LoansDue
            onChat={(d) => { setDetail(d); setScreen('chat') }}
            onNew={() => setScreen('newloan')}
            onStaff={() => setScreen('staff')}
            onBack={() => setScreen('landing')}
          />
        )}
        {screen === 'staff' && <Staff onBack={() => setScreen('loans')} />}
        {screen === 'newloan' && (
          <NewLoan lender={lender} onCreated={() => setScreen('loans')} onBack={() => setScreen('loans')} />
        )}
        {screen === 'chat' && detail && (
          <Chat initial={detail} lender={lender} onExit={() => { setDetail(null); setScreen('loans') }} />
        )}
      </div>
    </main>
  )
}
