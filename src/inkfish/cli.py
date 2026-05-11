"""inkfish.cli — Typer-based command-line interface for the INKFISH engine.

Commands:
  version          Print the installed version.
  seed             Reset DB and load data/seed/world.json at tick_id=0.
  run              Run the simulation for N ticks.
  reset            Reset world to a given tick (deletes data beyond).
  list-snapshots   List all persisted snapshots.
  serve            Start the FastAPI dev server.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

app = typer.Typer(help="INKFISH simulation engine", no_args_is_help=True)
logger = logging.getLogger(__name__)


@app.callback()
def _setup_logging(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
) -> None:
    """Configure logging level before any command runs."""
    logging.basicConfig(
        level="DEBUG" if verbose else "INFO",
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )


@app.command()
def version() -> None:
    """Print version."""
    typer.echo("inkfish 0.1.0 (P0)")


@app.command()
def seed(
    seed_path: Path = typer.Option(  # noqa: B008
        Path("data/seed/world.json"),
        "--seed-path",
        help="Path to world seed JSON file",
    ),
) -> None:
    """Reset DB and load seed world at tick_id=0."""
    from inkfish.config import load_config
    from inkfish.storage.db import create_db_engine, init_db, make_session_factory
    from inkfish.storage.repository import Repository
    from inkfish.storage.snapshot import SnapshotManager
    from inkfish.world.seed_loader import seed_world

    settings, _sim_cfg = load_config()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    repo = Repository(sf)
    snapshots = SnapshotManager(sf)
    world = seed_world(seed_path, repo, snapshots)
    typer.echo(
        f"Seeded world: tick={world.tick_id}, "
        f"chars={len(world.characters)}, locs={len(world.locations)}"
    )


@app.command()
def run(
    ticks: int = typer.Option(10, "--ticks", "-n", help="Number of ticks to simulate"),
    from_tick: int | None = typer.Option(
        None,
        "--from-tick",
        help="Resume from this tick (loads world from snapshot). "
        "Defaults to the latest persisted tick.",
    ),
) -> None:
    """Run the simulation for N ticks."""
    from inkfish.config import load_config
    from inkfish.llm import DeepSeekClient
    from inkfish.storage.db import create_db_engine, init_db, make_session_factory
    from inkfish.storage.repository import Repository
    from inkfish.storage.snapshot import SnapshotManager
    from inkfish.tick.scheduler import run_simulation

    settings, sim_cfg = load_config()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    repo = Repository(sf)
    snapshots = SnapshotManager(sf)

    start = from_tick if from_tick is not None else (repo.get_latest_tick_id() or 0)
    world = snapshots.load_world(start)
    if not world.characters:
        typer.echo("No characters at start tick. Run `inkfish seed` first.", err=True)
        raise typer.Exit(code=1)

    client = DeepSeekClient(settings.deepseek_api_key, model=sim_cfg.model)
    actions = run_simulation(
        ticks,
        world=world,
        client=client,
        repo=repo,
        snapshots=snapshots,
        start_tick=start,
        sim_config=sim_cfg,
    )
    typer.echo(
        f"Simulation done: {len(actions)} actions across {ticks} ticks "
        f"(start={start}, end={start + ticks})."
    )


@app.command()
def reset(
    tick_id: int = typer.Argument(..., help="Reset world to this tick (deletes data beyond)"),
) -> None:
    """Reset world to a given tick (deletes data beyond)."""
    from inkfish.config import load_config
    from inkfish.storage.db import create_db_engine, init_db, make_session_factory
    from inkfish.storage.snapshot import SnapshotManager

    settings, _ = load_config()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    snapshots = SnapshotManager(sf)
    snapshots.reset(tick_id)
    typer.echo(f"Reset to tick {tick_id}. Data beyond removed (llm_logs preserved).")


@app.command("list-snapshots")
def list_snapshots() -> None:
    """List all persisted snapshots."""
    from inkfish.config import load_config
    from inkfish.storage.db import create_db_engine, init_db, make_session_factory
    from inkfish.storage.snapshot import SnapshotManager

    settings, _ = load_config()
    engine = create_db_engine(settings.db_url)
    init_db(engine)
    sf = make_session_factory(engine)
    snapshots = SnapshotManager(sf)
    infos = snapshots.list_snapshots()

    if not infos:
        typer.echo("No snapshots.")
        return

    typer.echo(f"{'tick':<6} {'timestamp':<28} {'parent':<8} {'chars':<6} {'actions':<7}")
    for s in infos:
        typer.echo(
            f"{s.tick_id:<6} {s.timestamp.isoformat():<28} "
            f"{str(s.parent_tick_id or '-'):<8} {s.char_count:<6} {s.action_count:<7}"
        )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)"),
) -> None:
    """Start FastAPI dev server."""
    import uvicorn

    uvicorn.run("inkfish.api.main:app", host=host, port=port, reload=reload)
