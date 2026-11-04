import { useEffect, useRef, useState, type FormEvent } from 'react'

type Loan = { name: string; phone: string; amount_due: number; due_date: string }
type Message = { role: 'agent' | 'borrower'; text: string }
type Payment = { date: string; amount: number }
type Turn = {
  message: Message
  outcome: string
  payments: Payment[]
  missed_payment_reason: string | null
  ended: boolean
  policy_issues: string[]
}
type StartResponse = { conversation_id: number; message: Message; prior_context: string | null }

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Badge label and color for each outcome Richie reports.
const OUTCOMES: Record<string, { label: string; tone: 'neutral' | 'good' | 'warn' | 'stop' }> = {
  in_progress: { label: 'In progress', tone: 'neutral' },
  promise_to_pay: { label: 'Promise to pay', tone: 'good' },
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
  dispute: 'The borrower disputed the debt. Collection is paused until the lender sends written verification (FDCPA §809).',
  stop_request: 'The borrower asked for no further contact (FDCPA §805(c)).',
  attorney: 'The borrower is represented by an attorney. Contact the attorney only (FDCPA §805(a)(2)).',
  wrong_person: "This isn't the borrower. Don't discuss the debt with them (FDCPA §805(b)).",
  escalated: "Handed to the lender's team.",
}

const money = (n: number) => `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
const day = (iso: string) =>
  new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
const firstName = (name: string) => name.split(' ')[0]

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    const detail = data.detail
    const msg = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
      : detail || `Request failed (${res.status})`
    throw new ApiError(res.status, msg)
  }
  return data as T
}

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
  ['Reaches out', 'Richie opens with the debt-collection notice the law requires, and asks when the borrower can pay.'],
  ['Negotiates in policy', 'Offers only what you allow — pay in full, split into installments, or a short extension — and pins down exact dates and amounts.'],
  ['Logs the outcome', 'Every promise, dispute and opt-out is saved as data you can act on later.'],
]

const FEATURES: [string, string][] = [
  ['Follows the FDCPA', 'No threats, honest amounts, right-party contact — §§805–809 built into every message.'],
  ['Honors opt-outs', "Stops on request or when an attorney is involved, and won't contact them again."],
  ['Pauses on disputes', 'Flags the account and holds collection until written verification is sent.'],
  ['Remembers last time', "Recalls a borrower's prior promise and open balance on the next conversation."],
  ['Stays on your policy', "Agreed plans are re-checked against your limits — not taken on the model's word."],
  ['Decisions as data', 'Outcomes and promised payments are stored so you can query and follow up.'],
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
              Clovefi is AI-powered collections — Richie reaches out to borrowers in late-stage collections, negotiates a payment within your policy, and
              follows the FDCPA on every message — on behalf of {lender}.
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
              <div className="pv agent">Hi Jordan, your payment of $450.00 is past due. When can you pay?</div>
              <div className="pv borrower">I lost some shifts — can I split it?</div>
              <div className="pv agent">Of course. $150 on Feb 2 and $300 on Feb 20 works and fits our policy — you're all set.</div>
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

/* ---------- Collection form ---------- */

function CollectionForm({
  lender,
  onStarted,
  onBack,
}: {
  lender: string
  onStarted: (loan: Loan, res: StartResponse) => void
  onBack: () => void
}) {
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [amount, setAmount] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [error, setError] = useState('')
  const [blocked, setBlocked] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    setBlocked('')
    const loan: Loan = { name: name.trim(), phone: phone.trim(), amount_due: Number(amount), due_date: dueDate }
    setBusy(true)
    try {
      const res = await post<StartResponse>('/api/start', loan)
      onStarted(loan, res)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setBlocked(err.message)
      else setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel">
      <button className="back" onClick={onBack}><BackIcon /> Back</button>
      <h2>New collection</h2>
      <p className="panel-sub">Enter the borrower and the past-due payment. Richie opens the conversation; you reply as the borrower.</p>
      {blocked ? (
        <div className="blocked">
          <strong>Can't start this chat.</strong>
          <p>{blocked}</p>
          <button className="btn-blue" onClick={() => setBlocked('')}>Edit details</button>
        </div>
      ) : (
        <form className="fields" onSubmit={submit}>
          <label>
            Borrower name
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
                <input type="number" step="0.01" min="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="450.00" required />
              </div>
            </label>
            <label>
              Due date
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} required />
            </label>
          </div>
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-blue" disabled={busy}>{busy ? 'Starting…' : 'Start conversation'}</button>
          <p className="lender-note">On behalf of {lender}</p>
        </form>
      )}
    </div>
  )
}

/* ---------- Chat ---------- */

function Chat({
  loan,
  opener,
  conversationId,
  priorContext,
  lender,
  onNew,
}: {
  loan: Loan
  opener: Message
  conversationId: number
  priorContext: string | null
  lender: string
  onNew: () => void
}) {
  const [messages, setMessages] = useState<Message[]>([opener])
  const [draft, setDraft] = useState('')
  const [typing, setTyping] = useState(false)
  const [error, setError] = useState('')
  const [turn, setTurn] = useState<Omit<Turn, 'message'> | null>(null)
  const ended = turn?.ended ?? false
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, typing, turn])

  async function send(e: FormEvent) {
    e.preventDefault()
    const text = draft.trim()
    if (!text || typing || ended) return
    const next: Message[] = [...messages, { role: 'borrower', text }]
    setMessages(next)
    setDraft('')
    setError('')
    setTyping(true)
    try {
      const { message, ...rest } = await post<Turn>('/api/reply', { conversation_id: conversationId, text })
      setMessages([...next, message])
      setTurn(rest)
    } catch (err) {
      setError(`Richie couldn't reply, try again. (${(err as Error).message})`)
      setMessages(messages) // drop the unanswered message so it can be resent
      setDraft(text)
    } finally {
      setTyping(false)
    }
  }

  const badge = OUTCOMES[turn?.outcome ?? 'in_progress'] ?? OUTCOMES.in_progress
  const showSummary = turn && (turn.payments.length > 0 || turn.missed_payment_reason || turn.policy_issues.length > 0)

  return (
    <div className="chat-card">
      <header className="chat-head">
        <span className="head-avatar">R</span>
        <div className="head-text">
          <strong>Richie</strong>
          <span><i className="online" /> {lender} · automated assistant</span>
        </div>
        <button className="head-btn text" onClick={onNew}>New collection</button>
      </header>

      <div className="loan-strip">
        <span><strong>{loan.name}</strong> · {money(loan.amount_due)} due {day(loan.due_date)}</span>
        <span className={`badge ${badge.tone}`}>{badge.label}</span>
      </div>

      <div className="messages">
        {priorContext && (
          <div className="recall"><b>Richie remembers</b> {priorContext}</div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'agent' && <span className="avatar" aria-hidden="true">R</span>}
            <div className="bubble">{m.text}</div>
          </div>
        ))}
        {typing && (
          <div className="msg agent">
            <span className="avatar" aria-hidden="true">R</span>
            <div className="bubble dots" aria-label="Richie is typing"><i /><i /><i /></div>
          </div>
        )}
        {showSummary && (
          <div className="summary">
            {turn.payments.length > 0 && (
              <div><b>Agreed</b> {turn.payments.map((p) => `${money(p.amount)} on ${day(p.date)}`).join(' · ')}</div>
            )}
            {turn.missed_payment_reason && <div><b>Reason</b> {turn.missed_payment_reason}</div>}
            {turn.policy_issues.map((issue) => (
              <div key={issue} className="error">⚠ Outside policy: {issue}</div>
            ))}
          </div>
        )}
        <div ref={endRef} />
      </div>

      {error && <p className="error pad">{error}</p>}
      {ended ? (
        <div className="ended">
          <b>Conversation ended.</b> {ENDED_NOTE[turn!.outcome]}
        </div>
      ) : (
        <form className="composer" onSubmit={send}>
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder={`Reply as ${firstName(loan.name)}…`} autoFocus />
          <button type="submit" className="send" disabled={typing || !draft.trim()} aria-label="Send">
            <SendIcon />
          </button>
        </form>
      )}
    </div>
  )
}

/* ---------- App ---------- */

type Screen = 'landing' | 'form' | 'chat'
type Session = { loan: Loan; opener: Message; conversationId: number; priorContext: string | null }

export default function App() {
  const [lender, setLender] = useState('State Bank of Elytra')
  const [screen, setScreen] = useState<Screen>('landing')
  const [session, setSession] = useState<Session | null>(null)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((c) => c.lender_name && setLender(c.lender_name))
      .catch(() => {})
  }, [])

  useEffect(() => {
    document.title = 'Clovefi'
  }, [])

  if (screen === 'landing') {
    return (
      <main className="app">
        <Landing lender={lender} onInitiate={() => setScreen('form')} />
      </main>
    )
  }

  return (
    <main className="app">
      <header className="topbar">
        <button className="topbar-logo" onClick={() => { setScreen('landing'); setSession(null) }}>
          <Wordmark />
        </button>
      </header>

      <div className="stage">
        {screen === 'form' && (
          <CollectionForm
            lender={lender}
            onBack={() => setScreen('landing')}
            onStarted={(loan, res) => {
              setSession({ loan, opener: res.message, conversationId: res.conversation_id, priorContext: res.prior_context })
              setScreen('chat')
            }}
          />
        )}
        {screen === 'chat' && session && (
          <Chat
            loan={session.loan}
            opener={session.opener}
            conversationId={session.conversationId}
            priorContext={session.priorContext}
            lender={lender}
            onNew={() => { setSession(null); setScreen('form') }}
          />
        )}
      </div>
    </main>
  )
}
