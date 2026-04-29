# LogX Functional POC (Mock Source)

This implementation starts with a functionality-first POC:

- FastAPI backend
- NiceGUI frontend
- Mock Zerodha-shaped JSON events (no real third-party API calls yet)
- Trade lifecycle: pending_entry -> active -> pending_exit -> complete
- Node capture: fixed tags, custom tags, sliders, note, image attachments
- Phase 1 implemented: node state serialization + embeddings + vector persistence
- Weighted quality scoring: normalized category-weighted trade score (0..100)

## Structure

- `backend/` FastAPI app and SQLite DB
- `frontend/` NiceGUI app

## Run Backend

1. Install dependencies:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

2. Start API server:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --reload
```

API base: `http://localhost:8000/api/v1`

## Use FastAPI Docs Directly (No Frontend)

You can run the full POC directly from Swagger UI:

1. Open docs:

```text
http://localhost:8000/docs
```

2. Create a pending trade with:
	- `POST /api/v1/mock/events/entry`

3. Capture nodes using docs-friendly endpoints:
	- `POST /api/v1/trades/{trade_id}/nodes/entry`
	- `POST /api/v1/trades/{trade_id}/nodes/mid`
	- `POST /api/v1/trades/{trade_id}/nodes/exit`

In these endpoints:
- Tag types are dropdown selectors per category.
- Sliders are numeric inputs (`0..10`) per dimension.
- Note remains text input.
- Screenshots/pictures are uploaded via file input (`files`).

4. Close trade lifecycle with:
	- `POST /api/v1/mock/events/exit`

5. Review results with:
	- `GET /api/v1/queue/pending`
	- `GET /api/v1/journeys`
	- `GET /api/v1/journeys/{journey_id}`

## Run Frontend

1. Install dependencies:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m pip install -r frontend/requirements.txt
```

2. Start NiceGUI frontend:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe app.py
```

Frontend URL: `http://localhost:8080`

When the NiceGUI app opens in the browser, it automatically tries to start the local backend if `API Base URL` points to `localhost` or `127.0.0.1` and `/health` is not reachable.

## Core Endpoints

- `POST /api/v1/mock/events/entry`
- `POST /api/v1/mock/events/exit`
- `GET /api/v1/queue/pending`
- `POST /api/v1/trades/{trade_id}/nodes`
- `PUT /api/v1/trades/{trade_id}`
- `GET /api/v1/journeys`
- `GET /api/v1/tags/categories`
- `GET /api/v1/tags`
- `POST /api/v1/tags/custom`

## Weighted Trade Scoring

Scoring uses six weighted taxonomy categories:

- Direction (5), Strategy (25), Market (15), Execution (30), Quality (20), Outcome (5)

Per-category contribution:

- `(tag_score / max_tag_score_in_category) * category_weight`

Total trade score is the sum across categories and is persisted as `computed_quality_score` on each trade.
The score is recalculated automatically when nodes are created (`POST /trades/{id}/nodes`) or when node tags are updated (`PUT /trades/{id}`).

## Phase 1 (Embeddings & Storage)

When an `entry` or `mid` node is submitted:

- A dense deterministic text representation is generated from fixed tags, sliders, and note.
- An embedding vector is generated (deterministic by default; Azure OpenAI supported via env config).
- The embedding is stored in the relational table `node_embeddings`.

When an `exit` node is submitted:

- Existing embeddings for that trade are updated with the final trade PnL (`eventual pnl`).

Vector store backend:

- `VECTOR_STORE_BACKEND=database` stores vectors only in DB (default, test-friendly).
- `VECTOR_STORE_BACKEND=opensearch` attempts OpenSearch upsert per embedding while keeping node capture non-blocking on sync failure.

## Phase 2 (Behavioral Clustering Batch Job)

Implemented components:

- Data extraction from completed trades using persisted node embeddings and eventual PnL.
- Dimensionality reduction using UMAP when available (with deterministic fallback when not installed).
- Dense-cluster detection using HDBSCAN when available (with deterministic fallback when not installed).
- Centroid computation and persistence to `behavioral_profiles`:
	- Sweet Spot centroid = cluster with highest positive average PnL
	- Danger Zone centroid = cluster with lowest negative average PnL

Endpoints:

- `POST /api/v1/behavior/clustering/run`
	- `run_in_background=false` executes immediately and returns cluster summary.
	- `run_in_background=true` schedules via FastAPI BackgroundTasks.
- `GET /api/v1/behavior/profile`
	- Returns current `sweet_spot_centroid` and `danger_zone_centroid`.

## Phase 3 (Real-Time Intervention)

For `entry` and `mid` node capture requests:

- Backend computes embedding immediately and measures cosine similarity against `danger_zone_centroid`.
- If similarity exceeds a dynamic threshold, normal commit is paused and API returns:
	- `status=intervention_required`
	- `requires_confirmation=true`
	- generated intervention message and context metrics.
- Frontend shows a blocking confirmation modal and resubmits with `confirm_intervention=true` when user chooses to proceed.

LLM integration:

- Intervention generation uses OpenAI Chat Completions with model default `gpt-4.1-mini`.
- Provide `OPENAI_API_KEY` via env. If unavailable/error, backend falls back to deterministic templated message.

## Phase 4 (Retrospective RAG Engine)

Implemented components:

- Timeframe retriever that loads completed trades and formats entry->exit delta records (sliders, tags, notes, timeline).
- LangChain-style document conversion for retrieved trade histories (with lightweight fallback when LangChain is unavailable).
- Feature importance synthesis:
	- Uses XGBoost + SHAP when installed.
	- Falls back to deterministic proxy correlation/uplift metrics when those packages are unavailable.
- Behavioral drift metrics versus `sweet_spot_centroid` and `danger_zone_centroid`.
- High-context retrospective markdown synthesis using Azure OpenAI/OpenAI when configured, with deterministic fallback when not configured.
- Persistent report storage in `retrospective_reports`.

Endpoints:

- `POST /api/v1/behavior/retrospective/run`
	- Generates and stores a new retrospective report for a timeframe.
- `GET /api/v1/behavior/retrospective/reports`
	- Lists saved report summaries.
- `GET /api/v1/behavior/retrospective/reports/latest`
	- Returns the latest saved report.
- `GET /api/v1/behavior/retrospective/reports/{report_id}`
	- Returns full markdown and metrics payload for one report.

Frontend:

- NiceGUI now includes a **Retrospective Analysis** tab with:
	- timeframe/profile controls,
	- report generation action,
	- saved report history,
	- markdown report rendering,
	- drift and slider-delta visualizations.

## Run Tests

Install test dependencies:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m pip install -r backend/requirements-test.txt
```

Run backend tests:

```powershell
c:/Users/Lenovo/OneDrive/Desktop/logx/.venv/Scripts/python.exe -m pytest backend
```

Detailed functional coverage matrix:

- `backend/tests/FUNCTIONAL_TEST_MATRIX.md`

## Notes

- Attachments are stored in `backend/storage/attachments/`.
- Source mode is mock-only in this iteration.
- Replace mock adapter with live provider in the next integration phase.
