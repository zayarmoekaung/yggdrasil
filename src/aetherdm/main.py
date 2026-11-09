"""CLI entry point for AetherDM."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aetherdm.config import settings
from aetherdm.db.repository import Repository
from aetherdm.models import GameState
from aetherdm.seed_loader import SeedLoader
from aetherdm.session import SessionManager
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

    # Try to load persisted game state
    row = repo.conn.execute(
        "SELECT seed_name, current_round, state_snapshot FROM game_sessions WHERE id = '_current'"
    ).fetchone()
    if row:
        import json
        snapshot = json.loads(row["state_snapshot"])
        engine.game_state = GameState(
            session_id="_current",
            seed_name=row["seed_name"],
            current_round=row["current_round"],
            active_location_ids=snapshot.get("active_location_ids", []),
            global_flags=snapshot.get("global_flags", {}),
            world_history=snapshot.get("world_history", []),
        )

    return engine


def _get_session_manager() -> SessionManager:
    repo = _get_repo()
    sm = SessionManager(repo)
    return sm


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

        # Initialize game state for this seed
        engine = SimulationEngine(repo)
        engine.start_session(seed_data["name"])
        engine.game_state.active_location_ids = [loc["id"] for loc in seed_data["locations"]]
        engine.game_state.global_flags = seed_data.get("global_flags", {})
        # Persist so that _get_engine can pick it up
        engine.repo.conn.execute(
            "INSERT OR REPLACE INTO game_sessions (id, seed_name, current_round, state_snapshot) VALUES (?, ?, ?, ?)",
            ("_current", seed_data["name"], 0, json.dumps({"active_location_ids": engine.game_state.active_location_ids, "global_flags": engine.game_state.global_flags})),
        )
        engine.repo.conn.commit()
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


@app.command()
def save(session_name: str = typer.Argument(..., help="Name for the saved session")):
    """Save the current game state."""
    engine = _get_engine()
    sm = _get_session_manager()
    try:
        sm.save_session(session_name, engine.game_state)
        console.print(f"[green]Session saved:[/green] {session_name} (round {engine.game_state.current_round})")
    finally:
        engine.repo.close()
        sm.repo.close()


@app.command()
def load_session(session_name: str = typer.Argument(..., help="Name of the session to load")):
    """Load a saved game state."""
    sm = _get_session_manager()
    try:
        game_state = sm.load_session(session_name)
        if game_state is None:
            console.print(f"[red]Session not found:[/red] {session_name}")
            return
        console.print(f"[green]Session loaded:[/green] {session_name} (round {game_state.current_round})")
        console.print(f"  Seed: {game_state.seed_name}")
    finally:
        sm.repo.close()


@app.command()
def list_sessions():
    """List all saved sessions."""
    sm = _get_session_manager()
    try:
        sessions = sm.list_sessions()
        if not sessions:
            console.print("[yellow]No saved sessions.[/yellow]")
            return

        table = Table("Name", "Seed", "Round", "Saved At")
        for s in sessions:
            table.add_row(s["id"], s["seed_name"], str(s["round"]), s["saved_at"])
        console.print(table)
    finally:
        sm.repo.close()


@app.command()
def play(
    pc_id: str = typer.Argument("pc_1", help="Player character ID"),
):
    """Start interactive play mode."""
    engine = _get_engine()
    try:
        pc = engine._characters.get(pc_id)
        if pc is None:
            console.print(f"[red]Character not found:[/red] {pc_id}")
            raise typer.Exit(1)

        console.print(f"[bold green]=== AetherDM — Play Mode ===[/bold green]")
        console.print(f"Playing as: [bold]{pc.name}[/bold] ({pc_id})")
        console.print(f"Type 'help' for commands.\n")

        while True:
            current_loc = engine._locations.get(pc.location_id)
            if current_loc is None:
                console.print("[red]Player location not found![/red]")
                break

            # Show current location state
            console.print(f"\n[bold]=== Round {engine.game_state.current_round} | {current_loc.name} ===[/bold]")
            console.print(f"{current_loc.description}")
            if current_loc.environment.conditions:
                console.print(f"  Conditions: {', '.join(current_loc.environment.conditions)}")
            chars_here = [engine._characters[cid] for cid in current_loc.characters if cid in engine._characters and cid != pc_id]
            if chars_here:
                for ch in chars_here:
                    console.print(f"  {ch.name} ({ch.id}) — {ch.personality[:60]}...")
            console.print()

            # Get player command
            try:
                cmd = console.input("[bold yellow]>[/bold yellow] ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            parts = cmd.split(maxsplit=2)
            action = parts[0].lower()

            if action in ("q", "quit", "exit"):
                console.print("Goodbye!")
                break
            elif action == "help":
                console.print(
                    "[bold]Commands:[/bold]\n"
                    "  declare <intent>     — Declare an action\n"
                    "  next                 — Advance to next round\n"
                    "  move <location_id>   — Move to another location\n"
                    "  look                 — Look around\n"
                    "  status               — Show game status\n"
                    "  save <name>          — Save session\n"
                    "  q/quit/exit          — Quit"
                )
            elif action == "declare":
                if len(parts) < 2:
                    console.print("[red]Usage: declare <intent>[/red]")
                    continue
                intent = parts[1]
                pool = engine.repo.load_action_pool(pc.location_id, engine.game_state.current_round)
                if pool is None or pool.status == "resolved":
                    pool = engine.create_pool(pc.location_id)
                if pool.status == "open":
                    engine.add_action(pool, pc_id, intent)
                    console.print(f"[green]Declared:[/green] {intent}")
                else:
                    console.print(f"[yellow]Pool is {pool.status}.[/yellow]")
            elif action == "next":
                engine.next_round()
                # Resolve all locations
                for loc_id in list(engine._locations.keys()):
                    pool = engine.create_pool(loc_id)
                    # Auto-declare NPC actions
                    loc = engine._locations.get(loc_id)
                    if loc:
                        for ch_id in loc.characters:
                            ch = engine._characters.get(ch_id)
                            if ch and ch.type == "npc" and ch.goals:
                                engine.add_action(pool, ch_id, ch.goals[0])
                    engine.lock_pool(loc_id)
                    effects = engine.resolve_pool(pool)
                    narrative = engine.get_narrative(pool, effects)
                    console.print(narrative)
                    console.print()
            elif action == "move":
                if len(parts) < 2:
                    console.print("[red]Usage: move <location_id>[/red]")
                    continue
                target_id = parts[1]
                if target_id not in engine._locations:
                    console.print(f"[red]Location not found:[/red] {target_id}")
                    continue
                # Check if connected (or allow free movement for now)
                pc.location_id = target_id
                engine.repo.save_character(pc)
                # Reload to update location's character list
                engine._load_world_state()
                console.print(f"[green]Moved to:[/green] {engine._locations[target_id].name}")
            elif action == "look":
                console.print(f"[bold]{current_loc.name}[/bold]: {current_loc.description}")
                if current_loc.environment.conditions:
                    console.print(f"  Conditions: {', '.join(current_loc.environment.conditions)}")
            elif action == "status":
                console.print(f"Round: {engine.game_state.current_round}")
                console.print(f"Seed: {engine.game_state.seed_name}")
                console.print(f"Location: {current_loc.name}")
            elif action == "save":
                if len(parts) < 2:
                    console.print("[red]Usage: save <name>[/red]")
                    continue
                session_name = parts[1]
                sm = _get_session_manager()
                try:
                    sm.save_session(session_name, engine.game_state)
                    console.print(f"[green]Saved:[/green] {session_name}")
                finally:
                    sm.repo.close()
            else:
                console.print(f"[red]Unknown command:[/red] {action}. Type 'help' for commands.")
    finally:
        engine.repo.close()


cli = app

if __name__ == "__main__":
    app()
