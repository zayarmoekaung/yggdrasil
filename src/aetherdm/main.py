"""CLI entry point for AetherDM."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aetherdm.config import settings
from aetherdm.db.repository import Repository
from aetherdm.seed_loader import SeedLoader
from aetherdm.simulation.engine import SimulationEngine

app = typer.Typer(help="AetherDM — AI-powered text-based D&D engine", rich_markup_mode="rich")
console = Console()


def _get_repo() -> Repository:
    repo = Repository(settings.db_path_pathlib)
    repo.connect()
    return repo


def _get_engine() -> SimulationEngine:
    repo = _get_repo()
    engine = SimulationEngine(repo)
    engine._load_world_state()
    return engine


@app.command()
def load(seed: Path = typer.Argument(..., help="Path to a seed JSON file")):
    """Load a world seed into the database."""
    if not seed.exists():
        console.print(f"[red]Seed file not found:[/red] {seed}")
        raise typer.Exit(1)

    repo = _get_repo()
    try:
        loader = SeedLoader(repo)
        seed_data = loader.load(seed)
        console.print(f"[green]Loaded seed:[/green] [bold]{seed_data['name']}[/bold]")
        console.print(f"  {len(seed_data['locations'])} locations, {len(seed_data['characters'])} characters")
    finally:
        repo.close()


@app.command()
def status():
    """Show current game status."""
    repo = _get_repo()
    try:
        locations = repo.load_all_locations()
        characters = repo.load_all_characters()

        console.print(f"[bold]Locations:[/bold] {len(locations)}")
        console.print(f"[bold]Characters:[/bold] {len(characters)}")
    finally:
        repo.close()


@app.command()
def locations():
    """List all loaded locations."""
    repo = _get_repo()
    try:
        locs = repo.load_all_locations()
        if not locs:
            console.print("[yellow]No locations loaded.[/yellow]")
            return

        table = Table("ID", "Name", "Tags", "Characters")
        for loc in locs:
            table.add_row(
                loc.id,
                loc.name,
                ", ".join(loc.tags),
                ", ".join(loc.characters) if loc.characters else "(none)",
            )
        console.print(table)
    finally:
        repo.close()


@app.command()
def characters():
    """List all loaded characters."""
    repo = _get_repo()
    try:
        chars = repo.load_all_characters()
        if not chars:
            console.print("[yellow]No characters loaded.[/yellow]")
            return

        table = Table("ID", "Name", "Type", "Location", "Conditions")
        for ch in chars:
            table.add_row(
                ch.id,
                ch.name,
                ch.type,
                ch.location_id,
                ", ".join(ch.conditions) if ch.conditions else "(none)",
            )
        console.print(table)
    finally:
        repo.close()


@app.command()
def init(seed_path: Path = typer.Option(None, "--seed", help="Optional: load a seed after init")):
    """Initialize the database (creates tables)."""
    repo = _get_repo()
    console.print(f"[green]Database initialized:[/green] {settings.db_path}")
    repo.close()

    if seed_path:
        load(seed_path)


@app.command()
def next_round(location: str = typer.Option("all", "--location", "-l", help="Location ID to resolve (default: all)")):
    """Advance to the next round and resolve all action pools."""
    engine = _get_engine()
    try:
        round_num = engine.next_round()
        console.print(f"\n[bold]=== Round {round_num} ===[/bold]\n")

        # Resolve pools for specified location(s)
        location_ids = [location] if location != "all" else list(engine._locations.keys())

        for loc_id in location_ids:
            pool = engine.create_pool(loc_id)

            # Auto-add actions for NPCs at this location (Phase 2 demo)
            loc = engine._locations.get(loc_id)
            if loc:
                for ch_id in loc.characters:
                    ch = engine._characters.get(ch_id)
                    if ch and ch.type == "npc" and ch.goals:
                        engine.add_action(pool, ch_id, ch.goals[0])

            # Lock and resolve
            engine.lock_pool(loc_id)
            effects = engine.resolve_pool(pool)

            # Get narrative from DM Agent (stored in resolution)
            narrative = engine.get_narrative(pool, effects)
            console.print(narrative)
            console.print()
    finally:
        engine.repo.close()


@app.command()
def declare(
    location: str = typer.Argument(..., help="Location ID"),
    character: str = typer.Argument(..., help="Character ID"),
    intent: str = typer.Argument(..., help="What the character wants to do"),
):
    """Declare an action for a character at a location."""
    engine = _get_engine()
    try:
        pool = engine.repo.load_action_pool(location, engine.current_round)
        if pool is None or pool.status == "resolved":
            pool = engine.create_pool(location)

        if pool.status == "open":
            engine.add_action(pool, character, intent)
            console.print(f"[green]Action declared:[/green] {character} → {intent}")
        else:
            console.print(f"[yellow]Pool is {pool.status} — cannot add actions.[/yellow]")
    finally:
        engine.repo.close()


@app.command()
def resolve(location: str = typer.Argument(..., help="Location ID to resolve")):
    """Resolve the action pool for a location."""
    engine = _get_engine()
    try:
        pool = engine.repo.load_action_pool(location, engine.current_round)
        if pool is None:
            console.print(f"[yellow]No pool found for {location} at round {engine.current_round}.[/yellow]")
            return

        engine.lock_pool(location)
        effects = engine.resolve_pool(pool)
        narrative = engine.get_narrative(pool, effects)
        console.print(narrative)
    finally:
        engine.repo.close()


cli = app

if __name__ == "__main__":
    app()
