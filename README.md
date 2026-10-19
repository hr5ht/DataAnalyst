# ai-data-analyst

Ask questions about a CSV in plain English. Calculations run in pandas; the LLM picks the analysis and explains the result.

## Running locally

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

Asking questions needs a Groq API key. Get a free one at https://console.groq.com/keys and set `GROQ_API_KEY` in `.env`.

## Tests

```
pytest
```
