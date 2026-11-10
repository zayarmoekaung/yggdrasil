# AetherDM

AI-powered text-based D&D engine. A simulation-driven game where NPCs act autonomously, locations evolve in the background, and a DM Agent (LLM-powered) resolves conflicting actions into narrative outcomes.

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Agent Orchestration | LangGraph |
| LLM Interface | OpenAI SDK (Qwen cloud via OpenAI-compatible API + KoboldCPP local) |
| Database | SQLite (MVP) |
| Graph / Spatial | NetworkX |
| Validation | Pydantic v2 |
| CLI | Typer + Rich |
| Compact Serialization | BareSexp (s-expressions, ~5x fewer tokens than JSON) |

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

Edit `.env` to set your LLM provider:

```
LLM_MODE=qwen
QWEN_API_KEY=your-api-key-here
QWEN_MODEL=qwen-turbo
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
```

> **Important:** `QWEN_BASE_URL` is required. Without it, the OpenAI client defaults to `api.openai.com` and your Qwen key will be rejected.

## CLI Commands

### Admin Mode (standalone commands)

```bash
# Load a world seed
python -m aetherdm.main load seeds/worlds/village_fire.json

# Check current status
python -m aetherdm.main status

# List all locations
python -m aetherdm.main locations

# List all characters
python -m aetherdm.main characters

# Advance to next round (resolves pending pools, auto-declares NPC actions)
python -m aetherdm.main next-round

# Declare an action for a character
python -m aetherdm.main declare marketplace pc_1 "Fight the fire with buckets"

# Resolve a specific location's pool
python -m aetherdm.main resolve marketplace
```

### Play Mode (interactive)

```bash
# Start interactive play mode
python -m aetherdm.main play
```

Inside play mode:

| Command | Description |
|---|---|
| `declare <intent>` | Declare an action for your PC at the current location |
| `next` | Advance round: resolves all locations (verbose for yours, compact for background), creates fresh pools with NPC actions |
| `move <location_id>` | Move your PC to another location |
| `look` | Look around at current location |
| `status` | Show current round and seed info |
| `save <name>` | Save session |
| `help` | List commands |
| `q` / `quit` / `exit` | Quit play mode |

### Session Management

```bash
python -m aetherdm.main save my_session
python -m aetherdm.main load-session my_session
python -m aetherdm.main list-sessions
```

### Content Pipeline (Phase 4)

```bash
# Validate a seed file (schema + cross-reference checks) without loading
python -m aetherdm.main validate-seed seeds/worlds/village_fire.json

# Export current runtime state as a seed JSON
python -m aetherdm.main export-seed my_export.json --name "my_world" --description "Exported state"

# Load a world from separate component files (locations/, npcs/, pcs/)
python -m aetherdm.main load-components seeds/components/my_world/

# Split a monolithic seed into component files
python -m aetherdm.main export-components seeds/worlds/village_fire.json seeds/components/village_fire/
```

## Project Structure

```
src/aetherdm/
├── models/              # Pydantic schemas (LocationNode, Character, Event, Effect, ActionPool, DMResolution, GameState)
├── db/                  # SQLite schema, repository, NetworkX graph helpers
├── simulation/
│   ├── engine.py        # Game loop + DM Agent integration, BareSexp selective narration
│   ├── reaction.py      # Reaction score calculation
│   ├── eligibility.py   # Character eligibility filtering
│   └── effect_applier.py  # Effect application (deltas, appends, merges)
├── agents/
│   ├── dm_agent.py      # LLM-powered DM Agent (BareSexp context + JSON output + fallback)
│   ├── dm_graph.py      # LangGraph state graph for round lifecycle
│   └── prompts/
│       └── dm_v1.txt    # Versioned DM prompt
├── llm/
│   └── provider.py      # OpenAI SDK provider (Qwen + KoboldCPP)
├── baresexp_codec.py    # BareSexp serialization (location, character, pool, world state)
├── config.py            # Environment configuration
├── seed_loader.py       # JSON seed loader (with Pydantic validation)
├── seed_validator.py    # Seed validation engine (schema + cross-reference checks)
├── seed_exporter.py     # Runtime state → seed JSON exporter
├── component_seed_loader.py  # Component-based seed loading/exporting
├── session.py           # Session save/load manager
└── main.py              # CLI entry point (admin commands + interactive play mode)

seeds/
├── worlds/              # Monolithic seed JSON files
└── components/          # Component-based seeds (locations/, npcs/, pcs/)

tests/                   # 77 passing unit and integration tests
```

## How It Works

1. **Load a seed** → Locations and characters persist to SQLite
2. **Declare actions** → Added to the location's action pool for the current round
3. **Next round** → Pending pools are resolved first (so declared actions aren't lost), then the round advances
4. **DM Agent resolves** → Uses LLM (or rule-based fallback) to interpret conflicting actions, produces Effects
5. **Effects mutate state** → Location conditions change, character conditions accumulate, fire intensity reduces, etc.
6. **Selective narration** → In play mode, only your PC's location gets full narration; background locations resolve silently with compact BareSexp summaries

### BareSexp Compact Serialization

All internal state (world state, action pools, DM prompts/responses) uses BareSexp s-expressions instead of verbose JSON. This reduces LLM context token count by ~5x:

- Location + Character + ActionPool: ~96 tokens (vs ~500+ as JSON)
- Full world state (4 locations + 4 characters): ~400 tokens (vs ~2000+ as JSON)

## Development Phases

- **Phase 0** ✅ — Skeleton: models, DB schema, seed loader, LLM provider, CLI
- **Phase 1** ✅ — Core Simulation: reaction scoring, eligibility, effect applier, rule-based DM, round execution
- **Phase 2** ✅ — Real DM Agent: LangGraph lifecycle, prompt engineering, structured output, LLM contradiction resolution
- **Phase 3** ✅ — Full MVP: "village on fire" seed, 4 locations, 4 characters, save/load, playable CLI
- **Phase 4** ✅ — Content Pipeline: Pydantic seed validation, cross-reference checks, validate-seed CLI, state export, component seeds
- **Phase 5** ✅ — BareSexp compact state, selective PC narration, LLM wiring via OpenAI SDK
- **Phase 5+** — NPC agents, UI, PostgreSQL

## How to Test

```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=aetherdm
```

See [docs/development_plan.md](docs/development_plan.md) for the full spec.

## License

MIT
