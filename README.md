# CloveFi

AI-powered collections. From the **CloveFi** homepage, click "Initiate
collections" to see **Loans due**, open a chat on a member, and work the account
as the member. The design principle: **the code builds the payment plan; Richie
(Claude) only explains, classifies the reason, and confirms** — Richie never
makes up a dollar amount or a date. Everything persists; the server owns the
transcript.

## Setup (once)
```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # set ANTHROPIC_API_KEY (LENDER_NAME, DEFAULT_TIMEZONE already filled)

cd ../frontend
npm install
```

## Run (two terminals)
```bash
cd backend && .venv/bin/uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```
Open http://localhost:5173.

## How it works
- **Five screens:** CloveFi homepage → **Loans due** → **New collection** (adds a loan) / **Staff** → **Chat**.
- **Identity first:** the opener shares nothing about the account until the member confirms the last 4 digits of their phone (a stub to replace with OTP/SSO).
- **Code builds the plan:** installment amounts and dates come from `backend/plans.py` (integer cents), offered as the only policy-allowed options; Richie confirms. Nothing out of policy can be proposed.
- **Persistence** lives in `backend/clovefi.db` (SQLite, git-ignored): credit unions, policies, customers, loans, conversations, messages, payment plans, installments, contact attempts. The API key stays on the server.

## Docs
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — how the pieces fit, the request lifecycle.
- [`SCHEMA.md`](SCHEMA.md) — the database (tables, enums, DDL).
- [`FRONTEND.md`](FRONTEND.md) — the UI (screens, components, design system).
- [`COMPLIANCE.md`](COMPLIANCE.md) — FDCPA + Regulation F, and how each rule is enforced.
- [`AGENTS.md`](AGENTS.md) — layout, API and run notes for developers/agents.

## Note on data
The demo DB stores member names and phone numbers in plaintext — fine for local
testing, **not for real borrower data**. Production: encrypt the PII columns with
a KMS key plus a keyed HMAC blind index for phone lookups. Don't commit
`clovefi.db` (already git-ignored).
