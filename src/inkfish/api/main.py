"""inkfish.api.main — FastAPI application entry-point.

P0 stub: app is importable so `inkfish serve` doesn't crash.
Full routers are wired up in D9.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="INKFISH", version="0.1.0")
