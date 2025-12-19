from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from db import init_db
from api.routers import (
    filesystem,
    genres,
    ingest,
    presets,
    prompts,
    setlists,
    settings as settings_router,
    system,
    tracks
)

from config import settings

# Lifespan event to handle startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # DuckDBの初期化 (Raw SQLによるSequence/Table作成)
    yield

app = FastAPI(title="Djaly Backend API", lifespan=lifespan)

# CORS Configuration
origins = [
    f"http://localhost:{settings.FRONTEND_PORT}", # Tauri Dev Server
    f"http://127.0.0.1:{settings.FRONTEND_PORT}", # Tauri Dev Server (IP)
    f"http://localhost:{settings.DJALY_PORT}",    # Dynamic Port
    f"http://127.0.0.1:{settings.DJALY_PORT}",    # Dynamic Port
    "tauri://localhost",                          # Tauri Production (macOS)
    "https://tauri.localhost",                    # Tauri Production (Windows/Linux)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Root endpoint for health check
@app.get("/")
async def root():
    return {"message": "Djaly Backend API is running"}

# Include Routers
app.include_router(filesystem.router)
app.include_router(genres.router)
app.include_router(ingest.router)
app.include_router(presets.router)
app.include_router(prompts.router)
app.include_router(setlists.router)
app.include_router(settings_router.router)
app.include_router(system.router)
app.include_router(tracks.router)