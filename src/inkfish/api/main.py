"""inkfish.api.main — FastAPI application entry-point.

P0: 5 routers, 9 endpoints.  No SSE, no auth, CORS wide-open for dev.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from inkfish.api.routers import character, health, simulation, snapshot, tick

app = FastAPI(
    title="INKFISH API",
    version="0.1.0",
    description="Autonomous character simulation engine (P0 scaffolding).",
)

# CORS: wide-open for local dev.  Tighten in production (P6+).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health")
app.include_router(simulation.router, prefix="/simulation")
app.include_router(tick.router, prefix="/tick")
app.include_router(snapshot.router, prefix="/snapshot")
app.include_router(character.router, prefix="/character")
