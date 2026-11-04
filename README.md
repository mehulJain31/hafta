# Hafta (v0)

A one-time collections chat. Enter a borrower's name, amount due and due date. The agent, Richie, opens with a "your payment is due" message, then you type as the borrower and Claude replies as Richie. Nothing is saved: refreshing the page ends the chat.

## Setup (once)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env        # then put your key in ANTHROPIC_API_KEY

cd ../frontend
npm install
```

## Run (two terminals)

```bash
cd backend && .venv/bin/uvicorn main:app --reload --port 8000
cd frontend && npm run dev
```

Open http://localhost:5173.

## Files

- `backend/main.py`: the API (`POST /api/start` returns the opening message; `POST /api/reply` gets Richie's next reply). It keeps the API key on the server.
- `backend/agent.py`: Richie's instructions (system prompt) and the Claude call. Edit the prompt here.
- `frontend/src/App.tsx`: the loan form and the chat window.
