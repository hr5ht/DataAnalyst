# ai-data-analyst

Ask questions about a CSV in plain English. Calculations run in pandas; the LLM picks the analysis and explains the result.

## Running locally

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

## Tests

```
pytest
```
