"""inkfish.tick — tick scheduler: orchestrates per-tick character actions and snapshots."""

from .scheduler import run_simulation, run_tick

__all__ = ["run_simulation", "run_tick"]
