# ai-data-analyst

Ask questions about a CSV in plain English. Calculations run in pandas; the LLM picks the analysis and explains the result.

## Running locally

```
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000.

Asking questions needs a Groq API key. Get a free one at https://console.groq.com/keys and set `GROQ_API_KEY` in `.env`. Glossary search uses Gemini embeddings; get a key at https://aistudio.google.com/apikey and set `GEMINI_API_KEY`.

## Deploying to Vercel

The app runs on the free Hobby plan as a single Python function.

1. Import the repo at https://vercel.com/new. Vercel detects FastAPI from `requirements.txt` and `app/main.py`, so no extra config is needed.
2. Under Settings → Environment Variables, add `GROQ_API_KEY` and `GEMINI_API_KEY`, and set `APP_ENV` to `production`.
3. Deploy.

From the terminal instead:

```
npm i -g vercel
vercel link
vercel env add GROQ_API_KEY production
vercel env add GEMINI_API_KEY production
vercel --prod
```

Things to know on Vercel:

- Uploads are capped at 4 MB because Vercel rejects request bodies over 4.5 MB. Elsewhere, raise it with `MAX_UPLOAD_MB`.
- Uploaded datasets are kept in memory, so they are gone once Vercel recycles the instance. The page uploads the file again on its own when that happens.
- The glossary index is rebuilt with one Gemini call after each cold start.

## Asking questions

After uploading, ask a question in the box under the summary, or call the API directly:

```
curl -X POST http://127.0.0.1:8000/datasets/<dataset_id>/questions \
  -H "Content-Type: application/json" \
  -d '{"question": "Which country made the most revenue?"}'
```

The model only picks one of the built-in analyses and its arguments. pandas computes the result, and the written answer is checked so that every number in it appears in the result table; otherwise the plain step description is shown instead. Each response has a `status` (`answered`, `empty`, `clarify`, `unsupported` or `error`), the `answer`, the `operation` that ran, the `table`, an optional `chart`, any `warnings`, and the glossary `definitions` that were used. Provider failures return HTTP 503.

Up to `MAX_DATASETS` uploads (default 10) are kept, each for `DATASET_TTL_MINUTES` (default 60) after it was last used.

## Glossary

Column and metric definitions for the sample datasets live in `knowledge_base/*.json`. A glossary is used only when the uploaded CSV has all of its `columns`. Entries are embedded with Gemini (`gemini-embedding-2`) and searched with FAISS. The index is built in memory on first use, so editing a file and restarting the app rebuilds it.

## Tests

```
pytest
```
