import os
import sys

# 環境変数が既に設定されている場合は上書きしない (server.pyの設定を優先)
if "OMP_NUM_THREADS" not in os.environ:
    os.environ["OMP_NUM_THREADS"] = "1"
if "MKL_NUM_THREADS" not in os.environ:
    os.environ["MKL_NUM_THREADS"] = "1"
if "OPENBLAS_NUM_THREADS" not in os.environ:
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
if "VECLIB_MAXIMUM_THREADS" not in os.environ:
    os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
if "NUMEXPR_NUM_THREADS" not in os.environ:
    os.environ["NUMEXPR_NUM_THREADS"] = "1"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from api.routers import system, filesystem, ingest, settings, tracks, prompts, presets, setlists, genres
from services.ingestion_manager import ingestion_manager

app = FastAPI()

@app.on_event("startup")
def on_startup():
    init_db()

@app.on_event("shutdown")
def on_shutdown():
    print("Application shutting down...")
    ingestion_manager.shutdown()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(filesystem.router)
app.include_router(ingest.router)
app.include_router(settings.router)
app.include_router(tracks.router)
app.include_router(prompts.router)
app.include_router(presets.router)
app.include_router(setlists.router)
app.include_router(genres.router, prefix="/api/genres", tags=["genres"])
