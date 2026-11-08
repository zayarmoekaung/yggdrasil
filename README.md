# AetherDM

AI-powered text-based D&D engine. A simulation-driven game where NPCs act autonomously, locations evolve in the background, and a DM Agent resolves conflicting actions into narrative outcomes.

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Agent Orchestration | LangGraph |
| LLM Interface | LiteLLM (Qwen cloud + KoboldCPP local) |
| Database | SQLite (MVP) |
| Graph / Spatial | NetworkX |
| Validation | Pydantic v2 |
| CLI | Typer + Rich |

## Setup

### 1. Create a virtual environment

```bash
python -m venv .venv
```

### 2. Activate it

```bash
# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

Or from the frozen requirements:

```bash
pip install -r requirements.txt
pip install -e .
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` to set your LLM provider (Qwen API key or KoboldCPP URL).

## How to Test

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=aetherdm
```

## How to Run

```bash
# Load a world seed
python -m aetherdm.main load seeds/worlds/village_fire.json

# Check status
python -m aetherdm.main status

# List locations
python -m aetherdm.main locations

# List characters
python -m aetherdm.main characters

# Run the next round (auto-declares NPC actions)
python -m aetherdm.main next-round

# Declare a player action
python -m aetherdm.main declare marketplace pc_1 "Fight the fire with buckets"

# Resolve a specific location's pool
python -m aetherdm.main resolve marketplace
```

## Project Structure

```
src/aetherdm/
├── models/              # Pydantic schemas (LocationNode, Character, Event, Effect, ActionPool)
├── db/                  # SQLite schema, repository, NetworkX graph helpers
├── simulation/
│   ├── engine.py        # Game loop + rule-based pool resolution
│   ├── reaction.py      # Reaction score calculation
│   ├── eligibility.py   # Character eligibility filtering
│   └── effect_applier.py  # Effect application to state
├── agents/              # DM Agent (LangGraph nodes — Phase 2+)
├── llm/                 # LiteLLM provider (Qwen + KoboldCPP)
├── config.py            # Environment configuration
├── seed_loader.py       # JSON seed loader
└── main.py              # CLI entry point

seeds/worlds/            # JSON world definitions
tests/                   # Unit and integration tests (41 passing)
```

## Development Phases

- **Phase 0** ✅ — Skeleton: models, DB schema, seed loader, LLM provider, CLI
- **Phase 1** ✅ — Core Simulation: reaction scoring, eligibility, effect applier, rule-based DM, round execution
- **Phase 2** — Real DM Agent: LangGraph lifecycle, prompt engineering, structured output, LLM contradiction resolution
- **Phase 3** — Full MVP: "village on fire" seed, 3 locations, 4 NPCs, save/load, playable CLI
- **Phase 4** — Content Pipeline: data-driven seeds, validation, UI-ready structure
- **Phase 5+** — NPC agents, UI, PostgreSQL

See [docs/development_plan.md](docs/development_plan.md) for the full spec.

## License

MIT
