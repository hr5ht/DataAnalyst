# AI Data Analyst

Upload a CSV, review its data quality, and ask questions about it in plain English. Every number is computed with pandas. The LLM only chooses the analysis and explains the result.

**Live:** https://dataanalyst-hr5ht.vercel.app

## Demo login

| Username | Password |
| --- | --- |
| `demouser` | `demouserpass2026` |

You can browse the site without signing in. You'll be asked to sign in when you upload a file. The demo account allows 50 questions and 20 uploads a day, and the count resets at midnight UTC.

## Features

- **Profiling:** shows column types, ranges, missing values, duplicate rows and sample rows as soon as a file is uploaded.
- **Questions in plain English:** answers come with the result table, a chart, and the exact steps that were run.
- **Allowlisted analyses only:** the model can't run arbitrary code. It picks one of the built-in tools and fills in its arguments.
- **Grounded answers:** every number in a written answer must appear in the result table. If one doesn't, the app shows the plain step description instead.
- **Glossary lookup:** definitions for known datasets are retrieved with Gemini embeddings and FAISS, then passed to the planner.
- **Self-repair:** an invalid plan is sent back to the model once, along with the reason it failed.

## How it works

```
question → validate → retrieve definitions → plan (Groq) → run tool (pandas)
         → check result → explain (Groq) → verify numbers → response
```

The workflow is a LangGraph state graph. These are the analyses the planner can choose from:

| Tool | What it does |
| --- | --- |
| `profile_dataset` | Summary of the whole file |
| `list_columns` | Column names and types |
| `aggregate_data` | sum, mean, median, count, min or max, optionally grouped and filtered |
| `get_top_n` | Top or bottom N rows by a metric |
| `filter_data` | Rows matching conditions |
| `compute_correlation` | Pearson or Spearman correlation between two columns |
| `analyze_time_trend` | A metric over day, week, month, quarter or year |
| `clarify` / `unsupported` | Ask for more detail or decline the question |

## Tech stack

| Layer | Tools |
| --- | --- |
| API | FastAPI, Pydantic |
| Analysis | pandas |
| Agent | LangGraph, LangChain Groq (`openai/gpt-oss-120b`) |
| Retrieval | Gemini embeddings (`gemini-embedding-2`), FAISS |
| Frontend | HTML, CSS, JavaScript, Plotly |
| Hosting | Vercel (Python function) |

## Project structure

```
app/
  agent/        planner, intent schema, LangGraph workflow, explainer
  analysis/     profiler, pandas tools, chart specs
  api/          dataset and question routes
  retrieval/    glossary embedding and search
  static/       frontend
  auth.py       demo login and daily caps
  config.py     settings
  main.py       app entry point
knowledge_base/ glossary files for the sample datasets
tests/          unit and API tests
```

## Running locally

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | none | Needed for questions ([get a key](https://console.groq.com/keys)) |
| `GEMINI_API_KEY` | none | Needed for glossary search ([get a key](https://aistudio.google.com/apikey)) |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model used for planning and explaining |
| `EMBEDDING_MODEL` | `gemini-embedding-2` | Model used for glossary embeddings |
| `MAX_UPLOAD_MB` | `4` | Upload size limit |
| `DEMO_USERNAME`, `DEMO_PASSWORD` | none | Turn on the login. Leave both empty to turn it off |
| `DEMO_DAILY_QUESTIONS` | `50` | Questions allowed per day |
| `DEMO_DAILY_UPLOADS` | `20` | Uploads allowed per day |
| `APP_ENV` | `development` | Set to `production` when deployed |

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Status and configuration flags |
| `GET` | `/auth/session` | Current session and remaining usage |
| `POST` | `/auth/login` | Sign in |
| `POST` | `/auth/logout` | Sign out |
| `POST` | `/datasets` | Upload a CSV and get its profile |
| `GET` | `/datasets/{id}` | Fetch a stored dataset's profile |
| `POST` | `/datasets/{id}/questions` | Ask a question |

```bash
curl -X POST http://127.0.0.1:8000/datasets/<dataset_id>/questions \
  -H "Content-Type: application/json" \
  -d '{"question": "Which country made the most revenue?"}'
```

Each response contains:
- `status`: one of `answered`, `empty`, `clarify`, `unsupported` or `error`
- `answer`, the `operation` that ran, the result `table` and an optional `chart`
- `warnings` and the glossary `definitions` that were used

## Deploying to Vercel

1. Import the repo at https://vercel.com/new. Vercel detects FastAPI on its own.
2. Add `GROQ_API_KEY`, `GEMINI_API_KEY`, `DEMO_USERNAME` and `DEMO_PASSWORD`, and set `APP_ENV=production`.
3. Deploy.

Limits on the free plan:
- Uploads are capped at 4 MB because Vercel rejects request bodies over 4.5 MB.
- Datasets live in memory. If an instance is recycled, the page uploads the file again on its own.
- Each instance keeps its own usage count, and a cold start rebuilds the glossary index.

## Tests

```bash
pytest
```

The tests use scripted model responses and a fake embedder, so they make no API calls.
