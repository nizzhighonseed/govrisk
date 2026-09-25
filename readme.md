# Sankalp — AI-Powered Infrastructure Risk Intelligence Platform

A web application for monitoring government infrastructure projects, identifying risk early, and empowering officials with AI-driven insights. Built for the Smart India Hackathon 2026.

## Architecture

```
React Frontend (Vite + TypeScript)
      |
      | JWT authentication (Bearer token)
      v
FastAPI Backend
      |
      +----------------------+
      |                      |
      v                      v
   auth.db                sankalp.db
      |                      |
    users                projects
                         alerts
```

### Why two databases?

- **`auth.db`** — Authentication data (users, password hashes, roles). Kept separate so security-critical data is isolated from project data and can be backed up, migrated, or replaced independently.
- **`sankalp.db`** — Domain data (projects and alerts) that powers the risk monitoring product.

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4, React Router, Leaflet |
| Backend | FastAPI, SQLAlchemy 2 |
| Databases | SQLite (`auth.db` + `sankalp.db`) |
| Auth | JWT (access + refresh tokens), bcrypt password hashing |

## Roles

| Role | Capabilities |
|---|---|
| `admin` | All access + User Management (create/disable users, change roles) |
| `officer` | Project monitoring, analytics, reports |
| `analyst` | Project monitoring, analytics, AI assistant |
| `viewer` | Read-only access to the platform (default for new registrations) |

## Demo Accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@sankalp.gov.in` | `admin123` |
| Officer | `officer@sankalp.gov.in` | `officer123` |
| Analyst | `analyst@sankalp.gov.in` | `analyst123` |
| Viewer | `viewer@sankalp.gov.in` | `viewer123` |

> These are DEMO credentials only. Never use default secrets in production.

## Backend Setup

```bash
cd backend

# Install dependencies (uses Python 3.13)
pip install -r requirements.txt

# Seed the project database (sankalp.db)
python seed.py

# Seed the authentication database (auth.db) — idempotent, safe to rerun
python seed_auth.py

# Run the API server
uvicorn main:app --reload
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

The app will be available at `http://localhost:5173`.

## Environment Variables

Backend reads configuration from `backend/.env` (see `backend/.env.example`):

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./sankalp.db` | Project monitoring database |
| `AUTH_DATABASE_URL` | `sqlite:///./auth.db` | Authentication database |
| `JWT_SECRET_KEY` | dev value | Secret used to sign JWT tokens — set a strong value in production |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime in days |

Frontend reads `frontend/.env`:

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Backend API base URL |

## API Endpoints

### Authentication (`auth.db`)

| Method | Endpoint | Description | Access |
|---|---|---|---|
| POST | `/api/auth/register` | Create account (always role `viewer`) | Public |
| POST | `/api/auth/login` | Sign in, returns access + refresh tokens | Public |
| POST | `/api/auth/refresh` | Get a new access token | Refresh token |
| POST | `/api/auth/logout` | Log out | Authenticated |
| GET | `/api/auth/me` | Current user details | Authenticated |

### User Profile & Management

| Method | Endpoint | Description | Access |
|---|---|---|---|
| GET | `/api/users/me` | View own profile | Authenticated |
| PUT | `/api/users/me` | Update own `fullName`, `department`, `designation` | Authenticated |
| PUT | `/api/users/me/password` | Change own password | Authenticated |
| GET | `/api/users` | List all users | Admin |
| GET | `/api/users/{id}` | Get user by ID | Admin |
| PUT | `/api/users/{id}` | Update user | Admin |
| PATCH | `/api/users/{id}/role` | Change user role | Admin |
| PATCH | `/api/users/{id}/status` | Activate/deactivate user | Admin |

### Project Monitoring (`sankalp.db`)

All endpoints below require a valid JWT (returns `401` otherwise).

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/projects` | List all projects |
| GET | `/api/projects/{id}` | Project details |
| GET | `/api/alerts` | List early-warning alerts |
| GET | `/api/dashboard` | Portfolio KPIs + high-risk table |
| GET | `/api/analytics` | Sector analytics + risk matrix |
| GET | `/api/risk-map` | Geo data for the risk map |
| POST | `/api/assistant` | AI assistant query |
| GET | `/api/health` | Health check (public) |

## Authentication Flow

1. User signs in → backend verifies password (bcrypt) → issues **access token** (JWT, 30 min) + **refresh token** (JWT, 7 days)
2. Frontend stores tokens and attaches `Authorization: Bearer <accessToken>` to every request
3. On `401`, the frontend automatically refreshes the access token using the refresh token
4. Backend validates the JWT and checks the user's role before serving data
5. Logout clears token state client-side

## Security Notes

- Passwords are hashed with **bcrypt** — never stored or returned in plaintext
- Email has a unique index — duplicate account creation is rejected with `409`
- Scope limits authorization server-side: even if a non-admin manually calls `/api/users`, they receive `403`
- HTTP status codes: `401` unauthenticated, `403` authenticated but not authorized, `404` not found, `409` conflict, `422` validation
- The last remaining active admin cannot be deactivated or demoted

## HTTP Status Codes

| Code | Meaning |
|---|---|
| 401 | Unauthenticated — missing/expired/invalid token or bad credentials |
| 403 | Authenticated but role not permitted |
| 404 | Resource does not exist |
| 409 | Duplicate/conflict (e.g. email already registered) |
| 422 | Request validation failed |

## Project Structure

```
backend/
├── auth/
│   ├── database.py        # auth.db engine + session
│   ├── models.py          # User model
│   ├── schemas.py         # Pydantic auth schemas
│   ├── security.py        # bcrypt hashing + JWT create/verify
│   └── dependencies.py    # get_current_user, require_admin, require_roles
├── routers/
│   ├── auth.py            # register / login / refresh / logout / me
│   ├── users.py           # profile + password + admin user management
│   ├── projects.py
│   ├── alerts.py
│   ├── dashboard.py
│   ├── analytics.py
│   ├── risk_map.py
│   ├── assistant.py       # hybrid: deterministic + AI early-warning note
│   └── ai.py              # AI/early-warning endpoints
├── ai/                    # AI early-warning package (predictor, anomalies,
│   │                      # emerging risk, LLM service, feature engineering)
│   ├── predictor.py
│   ├── anomaly_detector.py
│   ├── emerging_risk.py
│   ├── llm_service.py
│   ├── feature_engineering.py
│   ├── ai_service.py
│   ├── schemas.py
│   └── prompts.py
├── services/risk_service.py
├── database.py            # sankalp.db engine + session
├── models.py              # Project/Alert/Update + AI models
├── schemas.py
├── seed.py                # seeds sankalp.db
├── seed_auth.py           # seeds auth.db (idempotent)
├── main.py                # FastAPI app + CORS + routers
├── sankalp.db
├── auth.db
└── .env / .env.example

frontend/
├── src/
│   ├── context/AuthContext.tsx   # auth state (user, login/logout, loading)
│   ├── components/
│   │   ├── auth/ProtectedRoute.tsx
│   │   └── layout/               # Sidebar, Topbar, AppLayout
│   ├── pages/
│   │   ├── Login.tsx
│   │   ├── Register.tsx
│   │   ├── Dashboard.tsx
│   │   ├── Projects.tsx
│   │   ├── ProjectDetails.tsx
│   │   ├── RiskMap.tsx
│   │   ├── Analytics.tsx
│   │   ├── Alerts.tsx
│   │   ├── Assistant.tsx
│   │   ├── Reports.tsx
│   │   └── Settings.tsx
│   └── services/api.ts           # centralized API helper (auto Bearer token)
```

## Production Readiness

This is an SIH MVP. Before production, consider:

- Strong `JWT_SECRET_KEY` via environment/config secrets
- PostgreSQL instead of SQLite
- Rate limiting on auth endpoints
- Email verification & password reset flows
- Refresh-token rotation with revocation
- OAuth/SSO, MFA, OTP as required by enterprise policy

## AI Early-Warning Layer

Sankalp combines a **deterministic rule engine** (unchanged - the single
source of truth for risk scores) with a **hybrid AI layer** that delivers
95-day early warnings without ever fabricating numbers.

### Architecture

```
project updates + alerts + risk inputs
            │
            ▼
  ai/feature_engineering.py     flat numeric feature vector (real data only)
            │
            ├──▶  ai/predictor.py          5 risk-event probabilities (0-1)
            ├──▶  ai/anomaly_detector.py   8 statistical deviation detectors
            └──▶  ai/emerging_risk.py      keyword + LLM risk extraction
            │
            ▼
  ai/ai_service.py              persistence, caching (TTL), alert dedup
            ▼
  routers/ai.py                 GET/POST /api/ai/... endpoints
```

### Design principles

- **No fake AI.** No ML model is claimed: the predictor is a transparent
  statistical model (`prediction_method` = `rule_statistical_fallback` when
  there is no update history, `hybrid` once >= 3 updates exist). `model_version`
  is `sankalp-ai-v1`.
- **LLM is optional and never trusted for numbers.** A provider is read from
  `AI_PROVIDER`/`AI_API_KEY` (OpenAI-compatible or Anthropic). It only
  classifies updates and enriches explanations; output must validate against a
  Pydantic schema, retries once, and falls back to deterministic keywords.
- **Cache + audit.** Every analysis is persisted (`ai_analyses`,
  `ai_predictions`, `ai_anomalies`, `ai_emerging_risks`) and served from cache
  for `AI_ANALYSIS_TTL_HOURS` (default 6).
- **Resilient.** LLM failure, network timeouts, or a missing key never breaks
  the app; AI endpoints return a friendly 503 and the deterministic engine
  keeps serving.
- **Deduplicated alerts.** Emerging risks raise `AI Emerging Risk` alerts only
  once per active category, bounded by `AI_ALERT_DEDUP_HOURS` (default 7 days).

### AI endpoints (all authenticated)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/ai/health` | LLM provider availability + fallback status |
| `GET /api/ai/projects/{id}/prediction` | Latest numeric prediction snapshot |
| `GET /api/ai/projects/{id}/anomalies` | Recent detected anomalies |
| `GET /api/ai/projects/{id}/emerging-risks` | Active emerging risks |
| `GET /api/ai/projects/{id}/explanation` | Grounded explanation of current vs future risk |
| `GET /api/ai/projects/{id}/insights` | Cached (or fresh on `?refresh=true`) full bundle |
| `POST /api/ai/projects/{id}/analyze` | Force a fresh full analysis (admin/officer) |
| `POST /api/ai/projects/{id}/updates/{update_id}/analyze` | Queued update-level analysis |

Posting a project update automatically triggers a background analysis with
alert creation when a HIGH/CRITICAL emerging risk is detected.

### Configuration

See `backend/.env.example`. Leave `AI_PROVIDER` empty to run deterministic-only;
set `AI_PROVIDER=openai` (or `anthropic`, `openrouter`, `azure`, `custom`),
`AI_API_KEY`, `AI_MODEL`, and optionally `AI_API_BASE`.

### Seeded early-warning scenarios

| Project | Scenario |
| --- | --- |
| PRJ-001 NH-48 | Stable high-way with mild recurring schedule pressure |
| PRJ-002 Freight Corridor | Emerging community / stakeholder opposition |
| PRJ-003 River Basin | Cost escalation + funding / resource stress (CRITICAL) |
| PRJ-004 Solar Park | Escalation path from supply-chain disruption |
| PRJ-005 Rural Roads | Improving trend (LOW) |
| PRJ-006 Regional Airport | Schedule-delay pressure from design/approval revisions |

Seeding also renders initial AI analysis snapshots for all six projects, so
the demo surfaces early warnings immediately after first `seed.py` run.
