"""
app/main.py -- FastAPI entrypoint (workstream M, plan section 13).

Pure JSON API (no more Jinja2/server-rendered templates, per plan section
13 -- the frontend is now a separate React SPA, workstream N) behind JWT
auth. Mounts every router other workstreams own, plus this workstream's own
(/profile, /companies, /preferences, /discovery, /jobs, /documents,
/statistics), and configures CORS so that SPA -- served from a different
origin (Netlify in production, a local Vite dev server during development)
-- can actually call this API from the browser.

Run locally with:
    uvicorn app.main:app --reload --port 5000
"""
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.auth import router as auth_router
from app.routes_companies import router as companies_router
from app.routes_documents import router as documents_router
from app.routes_jobs import router as jobs_router
from app.routes_profile import router as profile_router
from app.routes_statistics import router as statistics_router
from chat.routes import router as chat_router
from tracker.routes import router as tracker_router

app = FastAPI(title="Smart Job Search Engine API")

# ---------------------------------------------------------------------------
# CORS
#
# The React SPA (workstream N) is served from a different origin than this
# API (a local Vite dev server in development, a Netlify domain in
# production), so the browser enforces CORS on every request it makes here
# -- this needs to explicitly allow that origin or every fetch() from the
# frontend fails.
#
# Configure allowed origins for PRODUCTION via the CORS_ALLOWED_ORIGINS env
# var: a comma-separated list, e.g.
#     CORS_ALLOWED_ORIGINS=https://my-frontend.netlify.app,https://staging.my-frontend.netlify.app
# Falls back to common local dev origins (Vite's default 5173, plus 3000)
# when unset, so the API works against a local frontend out of the box.
# ---------------------------------------------------------------------------
_DEFAULT_DEV_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"
_allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _DEFAULT_DEV_ORIGINS).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)          # workstream G: /auth/*
app.include_router(tracker_router)       # workstream I: /tracker/*
app.include_router(profile_router)       # this workstream: /profile/*
app.include_router(companies_router)     # this workstream: /companies, /preferences
app.include_router(jobs_router)          # this workstream: /discovery/run, /jobs/*
app.include_router(documents_router)     # this workstream: /documents/*
app.include_router(statistics_router)    # this workstream: /statistics/*
app.include_router(chat_router)          # workstream H: /chat/*


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
