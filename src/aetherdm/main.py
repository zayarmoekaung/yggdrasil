"""CLI entry point for AetherDM."""

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from aetherdm.component_seed_loader import ComponentSeedLoader
from aetherdm.config import settings
from aetherdm.db.repository import Repository
from aetherdm.models import GameState
from aetherdm.seed_exporter import export_seed_to_file
from aetherdm.seed_loader import SeedLoader
from aetherdm.seed_validator import validate_seed
from aetherdm.session import SessionManager
from aetherdm.simulation.engine import SimulationEngine

app = typer.Typer(help="AetherDM — AI-powered text-based D&D engine", rich_markup_mode="rich")
console = Console()


def _get_repo() -> Repository:
    repo = Repository(settings.db_path_pathlib)
    repo.connect()
    return repo


def _get_engine() -> SimulationEngine:
    import os
    repo = _get_repo()
    debug = os.environ.get("AETHERDM_DEBUG", "").lower() in ("1", "true", "yes")
    engine = SimulationEngine(repo, debug=debug)
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


@app.command(name="validate-seed")
def validate_seed_cli(seed: Path = typer.Argument(..., help="Path to a seed JSON file")):
    """Validate a seed file without loading it. Reports all schema and cross-reference errors."""
    parsed, errors = validate_seed(seed)
    if errors:
        console.print(f"[red]Seed has {len(errors)} error(s):[/red]")
        for e in errors:
            console.print(f"  [red]✗[/red] {e}")
        raise typer.Exit(1)
    console.print(f"[green]Seed is valid:[/green] [bold]{parsed.name}[/bold]")
    console.print(f"  {len(parsed.locations)} locations, {len(parsed.characters)} characters")


@app.command()
def export_seed(
    output: Path = typer.Argument(..., help="Output path for the seed JSON file"),
    name: str = typer.Option("exported", "--name", "-n", help="Seed name"),
    description: str = typer.Option("", "--description", "-d", help="Seed description"),
):
    """Export the current runtime state as a seed JSON file."""
    repo = _get_repo()
    try:
        export_seed_to_file(repo, output, seed_name=name, description=description)
        console.print(f"[green]Seed exported:[/green] {output}")
    finally:
        repo.close()


@app.command()
def load_components(world_dir: Path = typer.Argument(..., help="Path to component world directory")):
    """Load a world from separate component files (locations/, npcs/, pcs/)."""
    if not world_dir.is_dir():
        console.print(f"[red]Directory not found:[/red] {world_dir}")
        raise typer.Exit(1)

    repo = _get_repo()
    try:
        loader = ComponentSeedLoader(repo)
        seed_data = loader.load(world_dir)
        console.print(f"[green]Loaded components from:[/green] [bold]{world_dir.name}[/bold]")
        console.print(f"  {len(seed_data['locations'])} locations, {len(seed_data['characters'])} characters")

        # Initialize game state
        engine = SimulationEngine(repo)
        engine.start_session(seed_data["name"])
        engine.game_state.active_location_ids = [loc["id"] for loc in seed_data["locations"]]
        engine.game_state.global_flags = seed_data.get("global_flags", {})
        engine.repo.conn.execute(
            "INSERT OR REPLACE INTO game_sessions (id, seed_name, current_round, state_snapshot) VALUES (?, ?, ?, ?)",
            ("_current", seed_data["name"], 0, json.dumps({"active_location_ids": engine.game_state.active_location_ids, "global_flags": engine.game_state.global_flags})),
        )
        engine.repo.conn.commit()
    finally:
        repo.close()


@app.command()
def export_components(
    seed: Path = typer.Argument(..., help="Path to a monolithic seed JSON file"),
    output_dir: Path = typer.Argument(..., help="Output directory for components"),
):
    """Split a monolithic seed file into component files (locations/, npcs/, pcs/)."""
    if not seed.exists():
        console.print(f"[red]Seed file not found:[/red] {seed}")
        raise typer.Exit(1)

    import json
    with open(seed, "r", encoding="utf-8") as f:
        seed_data = json.load(f)

    loader = ComponentSeedLoader(Repository(":memory:"))
    loader.export_components(seed_data, output_dir)
    console.print(f"[green]Components exported to:[/green] {output_dir}")


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
    """Advance to the next round and resolve all action pools.

    Any pending open pools from the previous round are resolved first,
    so declared actions are never lost between rounds.
    """
    engine = _get_engine()
    try:
        round_num = engine.game_state.current_round

        # Resolve any pending open pools from the previous round first
        location_ids = [location] if location != "all" else list(engine._locations.keys())

        for loc_id in location_ids:
            pending_pool = engine.repo.load_action_pool(loc_id, round_num)
            if pending_pool is not None and pending_pool.status == "open":
                engine.lock_pool(loc_id)
                pending_pool = engine.repo.load_action_pool(loc_id, round_num)
                effects = engine.resolve_pool(pending_pool)
                narrative = engine.get_narrative(pending_pool, effects)
                console.print(f"[dim][Round {round_num} — pending resolution][/dim]")
                console.print(narrative)
                console.print()

        # Now advance to the new round
        round_num = engine.next_round()
        console.print(f"\n[bold]=== Round {round_num} ===[/bold]\n")

        # Create fresh pools and auto-add NPC actions
        for loc_id in location_ids:
            pool = engine.create_pool(loc_id)

            loc = engine._locations.get(loc_id)
            if loc:
                for ch_id in loc.characters:
                    ch = engine._characters.get(ch_id)
                    if ch and ch.type == "npc" and ch.goals:
                        engine.add_action(pool, ch_id, ch.goals[0])

            console.print(f"  [dim]Pool created at {loc_id} — declare actions, then resolve or next-round.[/dim]")
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
        if pool is None or pool.status in ("resolved", "locked"):
            pool = engine.create_pool(location)

        if pool.status == "open":
            engine.add_action(pool, character, intent)
            console.print(f"[green]Action declared (round {engine.current_round}):[/green] {character} → {intent}")
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
                # Everything after "declare " is the intent
                intent = cmd[len("declare"):].strip()
                if not intent:
                    console.print("[red]Usage: declare <intent>[/red]")
                    continue
                pool = engine.repo.load_action_pool(pc.location_id, engine.game_state.current_round)
                if pool is None or pool.status in ("resolved", "locked"):
                    pool = engine.create_pool(pc.location_id)
                if pool.status == "open":
                    engine.add_action(pool, pc_id, intent)
                    console.print(f"[green]Declared (round {engine.game_state.current_round}):[/green] {intent}")
                else:
                    console.print(f"[yellow]Pool is {pool.status}.[/yellow]")
            elif action == "next":
                # Resolve any pending pool from the current round first (includes player's declared action)
                current_round = engine.game_state.current_round
                pc_loc_id = pc.location_id

                for loc_id in list(engine._locations.keys()):
                    pending_pool = engine.repo.load_action_pool(loc_id, current_round)
                    if pending_pool is not None and pending_pool.status == "open":
                        engine.lock_pool(loc_id)
                        pending_pool = engine.repo.load_action_pool(loc_id, current_round)
                        effects = engine.resolve_pool(pending_pool, pc_location_id=pc_loc_id)

                        # Only show verbose narrative for PC's location
                        if loc_id == pc_loc_id:
                            narrative = engine.get_narrative(pending_pool, effects)
                            console.print(narrative)
                        # Background locations: resolved silently, stored as baresexp

                # Now advance to the new round
                round_num = engine.next_round()
                console.print(f"\n[bold]=== Round {round_num} ===[/bold]\n")

                # Create fresh pools and auto-declare NPC actions
                for loc_id in list(engine._locations.keys()):
                    pool = engine.create_pool(loc_id)
                    loc = engine._locations.get(loc_id)
                    if loc:
                        for ch_id in loc.characters:
                            ch = engine._characters.get(ch_id)
                            if ch and ch.type == "npc" and ch.goals:
                                engine.add_action(pool, ch_id, ch.goals[0])

                # Show current location detail (PC's perspective)
                loc = engine._locations.get(pc.location_id)
                if loc:
                    console.print(f"[bold]{loc.name}:[/bold] {loc.description}")
                    if loc.environment.conditions:
                        console.print(f"  Conditions: {', '.join(loc.environment.conditions)}")
                    # Show if anything notable happened in the background
                    bg = engine.get_background_summary()
                    if bg != "(no background activity)":
                        console.print(f"\n[dim][Background activity][/dim]")
                        console.print(f"[dim]{bg}[/dim]")
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
