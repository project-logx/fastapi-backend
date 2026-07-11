# LogX Backend (FastAPI)

Backend-only overview for PPT use. This document highlights completed work and current capabilities in the FastAPI service.

## Architecture overview

- FastAPI app layer exposes REST endpoints for ingestion, capture, and retrieval.
- Service layer handles domain logic (mock ingestion, serialization, embeddings, scoring).
- SQLAlchemy models persist trades, nodes, tags, attachments, and behavioral profiles in SQLite.
- Attachments are stored on disk; metadata is stored in the database.
- Startup lifecycle seeds taxonomy and applies lightweight migrations.

### Data flow (happy path)

1. Mock entry event creates a pending trade and position state.
2. User captures entry and mid nodes with tags, sliders, notes, and optional attachments.
3. Node state is serialized, embedded, and stored for later analytics.
4. Exit event completes the lifecycle and finalizes trade score.
5. Journey endpoints return completed trade history for review.

## What has been built (completed work)

### Core platform and lifecycle
- FastAPI service with CORS, startup migrations, and taxonomy seeding.
- Trade lifecycle state machine: pending_entry -> active -> pending_exit -> complete.
- Mock event ingestion for entry/exit to simulate Zerodha-shaped events (no live API dependency).
- Journey listing and detail endpoints for completed trades.

### Data capture and scoring
- Node capture for entry/mid/exit with:
  - Fixed tags and custom tags
  - Sliders (0..10) with strict validation
  - Notes and file attachments (images)
- Weighted trade quality scoring across taxonomy categories (0..100).

### Embeddings and behavior foundations (Phase 1)
- Node state serialization for embeddings.
- Embedding generation with deterministic fallback and Azure OpenAI support.
- Vector persistence and trade-level embedding updates.

### Supporting modules
- Taxonomy and tag management (fixed categories, custom tags).
- Attachments storage and metadata.
- Retrospective report storage model (foundation for later phases).

### Test coverage
- Functional API tests mapped to product behavior:
  - Health and source-mode contracts
  - Mock event ingestion and idempotency
  - Queue and journey flows
  - Node capture rules and validation

## How each feature is used (stakeholder view)

- Mock ingestion: powers demos and QA without broker integration risk.
- Trade lifecycle: provides a reliable audit trail from entry to exit.
- Node capture: captures trader behavior at key decision points.
- Tags and sliders: turns qualitative judgment into structured, comparable data.
- Attachments: preserves evidence (screenshots) for later review.
- Quality scoring: delivers a single, easy-to-compare performance signal (0..100).
- Embeddings: lays the foundation for pattern discovery and personalization.
- Journeys: creates a clear narrative for coaching and performance review.
- Retrospective storage: supports weekly summaries and future AI insights.
- Health and metadata: ensures system readiness for client integration.

## API surface (high-level)

- Health and metadata
  - GET /api/v1/health
  - GET /api/v1/metadata

- Mock ingestion
  - POST /api/v1/mock/events/entry
  - POST /api/v1/mock/events/exit
  - POST /api/v1/mock/events/batch

- Trades and nodes
  - GET /api/v1/queue/pending
  - POST /api/v1/trades/{trade_id}/nodes/entry
  - POST /api/v1/trades/{trade_id}/nodes/mid
  - POST /api/v1/trades/{trade_id}/nodes/exit
  - PUT /api/v1/trades/{trade_id}

- Journeys
  - GET /api/v1/journeys
  - GET /api/v1/journeys/{journey_id}

- Tags
  - GET /api/v1/tags/categories
  - GET /api/v1/tags
  - POST /api/v1/tags/custom

- Retrospective
  - GET /api/v1/retrospective
  - POST /api/v1/retrospective

## Key backend components

- API routing: app/api/routes_*.py
- Data models: app/models.py
- Serialization: app/services/serialization.py
- Embeddings: app/services/embeddings.py
- Scoring: app/services/scoring.py
- Mock ingestion: app/services/mock_ingestion.py
- Migrations: app/services/schema_migrations.py

## Current phase status

- Phase 1 (State + embeddings): implemented
- Phase 2 (Behavioral clustering): planned
- Phase 3 (Real-time intervention): planned
- Phase 4 (Retrospective RAG): planned

## How to run the backend

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Start the API server:

```powershell
uvicorn app.main:app --app-dir app --reload
```

API base: http://localhost:8000/api/v1
Docs: http://localhost:8000/docs
