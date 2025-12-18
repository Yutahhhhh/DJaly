# Djaly Project Instructions

## Project Overview
Djaly is a local-first music library and DJ tool built with a React/Tauri frontend and a Python FastAPI backend. It uses DuckDB for data storage and integrates with Ollama and Essentia for AI/ML features.

## Architecture & Core Patterns

### Frontend (`src/`)
- **Framework**: React 19 + TypeScript + Vite.
- **Styling**: Tailwind CSS v4.
- **UI Components**: Located in `src/components/ui/`, following the shadcn/ui pattern (Radix UI primitives).
- **State/API**: 
  - API interaction is centralized in `src/services/api-client.ts`.
  - Use the `ApiClient` class for HTTP requests to the backend.
  - WebSockets are used for real-time updates (e.g., ingestion progress).

### Backend (`backend/`)
- **Framework**: FastAPI.
- **Database**: DuckDB, managed via SQLModel.
- **Structure**:
  - `api/routers/`: API route definitions.
  - `services/`: Business logic (e.g., `ingestion_manager.py`, `analysis/`).
  - `models.py`: SQLModel database schemas.
  - `db.py`: Database connection and initialization.
- **AI/ML**:
  - `essentia`: Used for audio feature extraction.
  - `ollama`: Local LLM integration for prompts and analysis.

### Data Flow
- **Communication**: Frontend talks to Backend on `http://127.0.0.1:8001`.
- **Storage**: Data is persisted in `db_data/djaly.duckdb`.
- **Music Files**: Stored/read from `music_data/` or user-configured paths.

## Development Workflow

### Startup
1. **Backend**: Run `pnpm backend:dev` (executes `backend/run_backend.sh`).
   - This sets up the python environment, env vars (`DB_PATH`, `OLLAMA_HOST`), and starts the server on port 8001.
2. **Frontend**: Run `pnpm dev` for the web view or `pnpm tauri dev` for the desktop app.

### Dependencies
- **Frontend**: Managed via `pnpm` (`package.json`).
- **Backend**: Managed via `pip` (`backend/requirements.txt`).
- **Environment**: Backend requires a virtual environment (`.venv`) created via `backend/setup.sh`.

## Coding Conventions

### Frontend
- Use functional components with TypeScript interfaces for props.
- Prefer `lucide-react` for icons.
- Use `clsx` and `tailwind-merge` for dynamic class names (see `src/lib/utils.ts`).
- **Do not** hardcode API URLs; use `API_BASE_URL` from `src/services/api-client.ts`.

### Backend
- Use Pydantic models for request/response schemas (`backend/schemas/`).
- Use SQLModel for database interaction.
- Ensure `ingestion_manager` is properly handled for long-running tasks.
- Respect the `backend/run_backend.sh` environment variables for paths.

## Key Files
- `src/services/api-client.ts`: Core API client wrapper.
- `backend/main.py`: Backend entry point and router inclusion.
- `backend/models.py`: Database schema definitions.
- `backend/run_backend.sh`: Source of truth for backend runtime environment.
