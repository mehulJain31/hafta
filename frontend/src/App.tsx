import { useEffect, useRef, useState, type FormEvent } from 'react'

type Loan = { name: string; amount_due: number; due_date: string }
type Message = { role: 'hafta' | 'borrower'; text: string }
type Payment = { date: string; amount: number }
type Turn = {
  message: Message
  outcome: string
  payments: Payment[]
  missed_payment_reason: string | null
  ended: boolean
  policy_issues: string[]
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
    // FastAPI validation errors come back as a list
    const msg = Array.isArray(detail)
      ? detail.map((d: { msg: string }) => d.msg.replace(/^Value error, /, '')).join('; ')
      : detail || `Request failed (${res.status})`
    throw new Error(msg)
  }
  return data as T
}

/* ---------- Icons ---------- */

function ChatIcon() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3.1-1.3-.6V16A2.5 2.5 0 0 1 4 13.5v-8Z" fill="currentColor" />
      <circle cx="8.5" cy="9.5" r="1.2" fill="#003262" />
      <circle cx="12" cy="9.5" r="1.2" fill="#003262" />
      <circle cx="15.5" cy="9.5" r="1.2" fill="#003262" />
    </svg>
  )
}

function CloseIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 12l16-8-6 16-2.5-6.5L4 12Z" fill="currentColor" />
    </svg>
  )
}

function Logo({ lender }: { lender: string }) {
  return (
    <div className="logo">
      <span className="logo-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="32" height="32">
          <rect width="32" height="32" rx="7" fill="#003262" />
          <path d="M16 6l9 5H7l9-5Z" fill="#FDB515" />
          <rect x="9" y="13" width="2.6" height="9" fill="#fff" />
          <rect x="14.7" y="13" width="2.6" height="9" fill="#fff" />
          <rect x="20.4" y="13" width="2.6" height="9" fill="#fff" />
          <rect x="7" y="23.5" width="18" height="2.5" fill="#FDB515" />
        </svg>
      </span>
      <span className="logo-text">{lender}</span>
    </div>
  )
}

/* ---------- Bank website (background) ---------- */

function BankSite({ lender, onOpenChat }: { lender: string; onOpenChat: () => void }) {
  return (
    <div className="site">
      <nav className="nav">
        <div className="wrap nav-inner">
          <Logo lender={lender} />
          <div className="nav-links">
            <a>Personal</a>
            <a>Auto Loans</a>
            <a>Business</a>
            <a>About</a>
          </div>
          <button className="btn-gold sm">Sign in</button>
        </div>
      </nav>

      <header className="hero">
        <div className="wrap hero-inner">
          <div className="hero-copy">
            <p className="eyebrow">Auto loans</p>
            <h1>Banking that keeps you moving.</h1>
            <p className="lede">
              Competitive rates, flexible payment options and real help when life gets in the way. Have a question about a
              payment? Our assistant Richie is here around the clock.
            </p>
            <div className="hero-actions">
              <button className="btn-gold" onClick={onOpenChat}>Chat with Richie</button>
              <button className="btn-outline">View loan rates</button>
            </div>
          </div>
          <div className="hero-card" aria-hidden="true">
            <div className="hc-row">
              <span>Auto loan</span>
              <span className="hc-tag">Active</span>
            </div>
            <div className="hc-amount">$18,240.00</div>
            <div className="hc-label">Remaining balance</div>
            <div className="hc-bar"><span style={{ width: '42%' }} /></div>
            <div className="hc-row muted">
              <span>Next payment</span>
              <span>$450.00</span>
            </div>
          </div>
        </div>
      </header>

      <section className="features wrap">
        {[
          ['Flexible payments', 'Split a payment or request a short extension when you need a little more time.'],
          ['Help, not pressure', 'Talk through options with Richie or our team, privately and respectfully.'],
          ['Know where you stand', 'See your balance, due dates and payment history in one place.'],
        ].map(([title, body]) => (
          <div className="feature" key={title}>
            <span className="feature-dot" />
            <h3>{title}</h3>
            <p>{body}</p>
          </div>
        ))}
      </section>

      <footer className="footer">
        <div className="wrap footer-inner">
          <span>© {new Date().getFullYear()} {lender}. Member FDIC. Equal Housing Lender.</span>
          <span>Demo site</span>
        </div>
      </footer>
    </div>
  )
}

/* ---------- Chat widget ---------- */

function SetupForm({ onStart }: { onStart: (loan: Loan, opener: Message) => void }) {
  const [name, setName] = useState('')
  const [amount, setAmount] = useState('')
  const [dueDate, setDueDate] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError('')
    const loan = { name: name.trim(), amount_due: Number(amount), due_date: dueDate }
    setBusy(true)
    try {
      const { message } = await post<{ message: Message }>('/api/start', loan)
      onStart(loan, message)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="setup" onSubmit={submit}>
      <div className="setup-intro">
        <h2>Start a demo chat</h2>
        <p>Enter the borrower's details. Richie will reach out about the payment, and you reply as the borrower.</p>
      </div>
      <label>
        Borrower name
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Jordan Lee" autoComplete="off" required />
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
      <button type="submit" className="btn-blue" disabled={busy}>{busy ? 'Starting…' : 'Start chat'}</button>
    </form>
  )
}

function Conversation({ loan, opener }: { loan: Loan; opener: Message }) {
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
      const { message, ...rest } = await post<Turn>('/api/reply', { loan, messages: next })
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
    <>
      <div className="loan-strip">
        <span>
          <strong>{loan.name}</strong> · {money(loan.amount_due)} due {day(loan.due_date)}
        </span>
        <span className={`badge ${badge.tone}`}>{badge.label}</span>
      </div>

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`msg ${m.role}`}>
            {m.role === 'hafta' && <span className="avatar" aria-hidden="true">R</span>}
            <div className="bubble">{m.text}</div>
          </div>
        ))}
        {typing && (
          <div className="msg hafta">
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
    </>
  )
}

function ChatWidget({ lender, open, setOpen }: { lender: string; open: boolean; setOpen: (o: boolean) => void }) {
  const [session, setSession] = useState<{ loan: Loan; opener: Message; key: number } | null>(null)

  return (
    <>
      <section className={`widget ${open ? 'open' : ''}`} aria-hidden={!open} aria-label="Chat with Richie">
        <header className="widget-head">
          <span className="head-avatar">R</span>
          <div className="head-text">
            <strong>Richie</strong>
            <span><i className="online" /> {lender} assistant</span>
          </div>
          {session && (
            <button className="head-btn text" onClick={() => setSession(null)}>New chat</button>
          )}
          <button className="head-btn" onClick={() => setOpen(false)} aria-label="Close chat"><CloseIcon /></button>
        </header>
        <div className="widget-body">
          {session ? (
            <Conversation key={session.key} loan={session.loan} opener={session.opener} />
          ) : (
            <SetupForm onStart={(loan, opener) => setSession({ loan, opener, key: Date.now() })} />
          )}
        </div>
      </section>

      <button className={`launcher ${open ? 'is-open' : ''}`} onClick={() => setOpen(!open)} aria-label={open ? 'Close chat' : 'Chat with Richie'}>
        {open ? <CloseIcon /> : <ChatIcon />}
      </button>
    </>
  )
}

export default function App() {
  const [lender, setLender] = useState('State Bank of Elytra')
  const [open, setOpen] = useState(false)

  useEffect(() => {
    fetch('/api/config')
      .then((r) => r.json())
      .then((c) => c.lender_name && setLender(c.lender_name))
      .catch(() => {})
  }, [])

  useEffect(() => {
    document.title = lender
  }, [lender])

  return (
    <>
      <BankSite lender={lender} onOpenChat={() => setOpen(true)} />
      <ChatWidget lender={lender} open={open} setOpen={setOpen} />
    </>
  )
}
