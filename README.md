# Clovefi

Clovefi is AI-powered collections. From the **Clovefi** landing page, click "Initiate collections", enter a borrower (name, phone, amount due, due date), and **Richie** opens the conversation. You reply as the borrower; Richie negotiates a payment within the lender's policy and follows the FDCPA on every message. Chats are saved to a database, so Richie remembers a borrower's last decision and won't re-contact someone who opted out.

## Setup (once)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then set ANTHROPIC_API_KEY (LENDER_NAME, DEFAULT_TIMEZONE already filled)

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

- **Three screens:** Clovefi landing → a "New collection" form → the chat.
- **The server owns the chat.** Each reply sends only a `conversation_id` and the new text; the backend rebuilds the history from the database, so the transcript isn't trusted from the browser.
- **Persistence** lives in `backend/clovefi.db` (SQLite, git-ignored): customers → loans → conversations → messages + promised payments. Timestamps are stored in UTC. The API key stays on the server.

## Files

- `backend/main.py` — the API (`/api/start`, `/api/reply`, `/api/conversations/{id}`, `/api/config`).
- `backend/agent.py` — Richie's instructions and the Claude call. Edit the prompt here.
- `backend/policies.py` — FDCPA rules and the lender's payment options (split / extension limits).
- `backend/models.py` / `db.py` / `store.py` — the database tables and persistence logic.
- `frontend/src/App.tsx` — the landing page, form and chat.

## Note on data

The demo database stores borrower names and phone numbers in plain text — fine for local testing, **not for real borrower data**. For production: encrypt the PII columns with a key from a KMS and add a keyed HMAC blind index for phone lookups. Don't commit `clovefi.db` (already git-ignored).
