"""CLI placeholder — populated in D8."""

import typer

app = typer.Typer(help="INKFISH simulation engine", no_args_is_help=True)


@app.command()
def version() -> None:
    """Print version."""
    print("inkfish 0.1.0 (P0)")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Start the INKFISH API server (stub — implemented in D9)."""
    print(f"inkfish serve {host}:{port} — not yet implemented (D9)")
