# LogX Functional POC (Mock Source)

This implementation starts with a functionality-first POC:

- FastAPI backend
- NiceGUI frontend
- Mock Zerodha-shaped JSON events (no real third-party API calls yet)
- Trade lifecycle: pending_entry -> active -> pending_exit -> complete
- Node capture: fixed tags, custom tags, sliders, note, image attachments
- Analytics intentionally deferred

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
- `GET /api/v1/journeys`
- `POST /api/v1/tags/custom`

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
