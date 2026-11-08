**Development Plan & Specs**  
For the AI-powered text-based D&D engine (codename working title: **AetherDM**)

This document is written so a coding agent can start implementing immediately.

---

### 1. Tech Stack (Final Decisions)

| Layer                    | Choice                          | Reason |
|--------------------------|----------------------------------|------|
| Language                 | Python 3.12+                    | Best LLM + agent ecosystem |
| Agent Orchestration      | **LangGraph**                   | Stateful, cyclic, multi-agent, perfect for rounds + DM |
| LLM Interface            | **LiteLLM**                     | Unified API for Qwen (cloud) + KoboldCPP (local OpenAI-compatible) |
| Structured DB            | **SQLite** (MVP) → PostgreSQL later | Zero config start, easy migration |
| Graph / Spatial          | SQL tables + **NetworkX** (in-memory) | Simple, fast enough, no extra service |
| Config / Seeds           | JSON files + Pydantic models    | Human + UI editable later |
| API / Interface (MVP)    | CLI + simple FastAPI later      | Start with CLI for speed |
| Validation & Schemas     | Pydantic v2                     | Everywhere |

---

### 2. High-Level Architecture

```
┌─────────────────────────────┐
│         Game Loop           │  (LangGraph State Graph)
│  Round → Phases → Resolve   │
└────────────┬────────────────┘
             │
     ┌───────▼────────┐
     │   DM Agent     │  (LangGraph node / subgraph)
     │  - Resolve pool│
     │  - Narrate     │
     │  - Emit Effects│
     └───────┬────────┘
             │
     ┌───────▼────────────────────────┐
     │     Simulation Core            │
     │  - Location Graph (NetworkX)   │
     │  - Action Pools                │
     │  - Reaction Score              │
     │  - Eligibility                 │
     │  - Effect Applier              │
     └───────┬────────────────────────┘
             │
     ┌───────▼────────┐
     │  Persistence   │  SQLite + JSON seeds
     └────────────────┘
```

---

### 3. Project Structure

```
aetherdm/
├── pyproject.toml
├── README.md
├── .env.example
├── seeds/                          # JSON definable content
│   ├── worlds/
│   │   └── village_fire.json
│   ├── locations/
│   ├── npcs/
│   └── pcs/
├── src/aetherdm/
│   ├── __init__.py
│   ├── main.py                     # CLI entry
│   ├── config.py
│   ├── models/                     # Pydantic schemas
│   │   ├── location.py
│   │   ├── character.py
│   │   ├── event.py
│   │   ├── action_pool.py
│   │   └── effect.py
│   ├── db/
│   │   ├── schema.sql
│   │   ├── repository.py
│   │   └── graph.py                # NetworkX helpers
│   ├── simulation/
│   │   ├── engine.py               # Main round loop
│   │   ├── reaction.py             # Score + ordering
│   │   ├── eligibility.py
│   │   └── effect_applier.py
│   ├── agents/
│   │   ├── dm_agent.py             # LangGraph DM
│   │   ├── npc_agent.py            # Optional later
│   │   └── prompts/
│   ├── llm/
│   │   └── provider.py             # LiteLLM wrapper (Qwen + Kobold)
│   └── utils/
└── tests/
```

---
Here’s a concrete draft of **1 → 2 → 3**.

---

### 1. Data Schemas

#### Location Node
```ts
LocationNode {
  id: string
  name: string
  description: string                    // short base description
  tags: string[]                         // e.g. ["urban", "market", "indoor"]
  
  // Spatial
  connections: {
    targetId: string
    type: "road" | "path" | "river" | "portal" | "secret" | "rumor"
    travelTime: number                   // base time cost
    propagationModifier: number          // how easily events travel (0.1–2.0)
  }[]

  // Local State
  environment: {
    conditions: string[]                 // ["on_fire", "flooded", "dark", ...]
    objects: ObjectInstance[]
    resources: Record<string, number>
    flags: Record<string, any>
  }

  // Occupants
  characters: string[]                   // character ids currently here

  // Simulation
  lastMutatedRound: number
  pendingEffects: Effect[]               // effects waiting to be applied
}
```

#### Character (PC & NPC share the base)
```ts
Character {
  id: string
  name: string
  type: "pc" | "npc"
  
  // Core
  locationId: string
  stats: Record<string, number>          // whatever system you want
  inventory: Item[]
  conditions: string[]                   // ["wounded", "hidden", "panicked"]
  
  // Agency
  personality: string                    // short high-signal description
  goals: string[]
  secrets: string[]
  quickness: number                      // used in Reaction Score (higher = faster)
  
  // Memory & Relationship
  memory: MemoryEntry[]                  // short rolling memory
  relationships: Record<string, number>  // characterId → disposition (-100 to 100)
  
  // Runtime
  lastActionRound: number
  currentPlan?: string
}
```

#### Event
```ts
Event {
  id: string
  round: number
  timeToken: number                      // optional finer ordering inside a round
  
  originLocationId: string
  actorId: string | "world" | "dm"
  
  type: "action" | "mutation" | "perception" | "system"
  intent: string                         // human-readable declared intention
  intensity: number                      // 0.0 – 10.0+
  
  // Propagation
  scope: "local" | "adjacent" | "region" | "global"
  remainingIntensity: number
  
  // Resolution
  mechanical?: {
    successLevel?: "critical" | "success" | "partial" | "failure" | "critical_failure"
    dice?: any
    tags?: string[]
  }
  
  effects: Effect[]                      // authorized state changes
  visibility: "public" | "local" | "private" | "secret"
}
```

#### Effect
```ts
Effect {
  targetType: "location" | "character" | "world" | "edge"
  targetId: string
  changes: Record<string, any>           // the actual mutations
  description: string                    // for logging / DM
}
```

#### Action Pool (per location / visibility scope)
```ts
ActionPool {
  locationId: string                     // or scopeId
  round: number
  actions: {
    characterId: string
    intent: string
    declaredOrder: number                // position in the declaration sequence
    reactionTo?: string[]                // event ids this was responding to
    focused: boolean                     // true = reacted to single highest event
  }[]
  
  status: "open" | "locked" | "resolved"
}
```

---

### 2. DM Agent – Pool Resolution Logic

When a location’s Action Pool is resolved (Phase 1 of the next Round), the DM Agent follows this process:

**Step 1 – Gather Context**
- Current state of the location and all characters in it
- Full list of declared actions in the pool (with their declaration order)
- Any spreading effects that just arrived from other locations
- Relevant personality, goals, and relationships

**Step 2 – Interpret Combined Intentions**
The DM looks at the set of actions as a whole and answers:

- Which actions support each other?
- Which actions directly contradict each other?
- Which actions are independent?
- Are there any physics / common-sense collisions? (two people trying to pick up the same object, one person blocking a door while another tries to flee through it, etc.)

**Step 3 – Apply Resolution Principles**
- Contradictory actions are allowed. The DM decides the actual outcome (one succeeds, both partially succeed, both fail, unexpected third outcome, etc.).
- Declaration order and Reaction Score can be used as soft priority, but are not absolute.
- Personality and goals should influence who is more likely to succeed or how far they push.
- The result must stay consistent with the current world state and previously established facts.

**Step 4 – Emit Effects**
The DM produces a list of `Effect`s that will be applied to:

- The location itself
- The characters involved
- Possibly neighboring locations (if the outcome has spreading consequences)

**Step 5 – Generate Narrative**
A concise narrative description of what actually happened is created for any observers (mainly the PCs if they are present or if the effects later reach them).

**Important rule**: The DM never invents major new permanent facts that are not supported by the actions + current state. It only interprets and resolves.

---

### 3. Seed → Runtime Mutation Pipeline

**Seed Phase (static data)**
```
SeedWorld
├── Location graph (nodes + connections)
├── Base environment & flags per location
├── Seed NPCs (with personality, goals, secrets, starting location)
├── Starting PC(s)
├── Global world flags & history summary
└── Initial events / starting situation
```

At game start these are loaded into the live runtime structures (`LocationNode`, `Character`, etc.).

**Runtime Mutation Rules**

1. **Only Effects can permanently change state**  
   Every lasting change must come from an `Effect` that was emitted by a resolved Event or by the DM during pool resolution.

2. **Mutation categories**
   - Local: changes only the current node or characters on it
   - Spreading: writes effects into neighboring nodes (with reduced intensity / delay)
   - Graph-level: can add/remove connections, create new nodes, or destroy nodes (rare, high-intensity only)
   - Character-level: inventory, conditions, memory, relationships, goals, location

3. **Background persistence**
   - Locations not currently observed by any PC still receive and apply Effects
   - Their Action Pools still form and resolve
   - All resulting state is saved
   - When a PC later enters that location (or effects propagate to them), they experience the already-mutated state

4. **Seed vs Living State**
   - The original seed is never overwritten
   - The live state is a divergent copy that keeps mutating
   - You can always compare live state against seed if you need to know “what changed”

5. **Safe mutation channels**
   - Node environment & flags
   - Character memory, relationships, conditions, inventory, goals
   - World-level flags
   - Connection properties (rarely)
   - Creation of new low-importance NPCs or objects (allowed)
   - Creation of major new locations or named NPCs (should usually require explicit DM / high-intensity justification)

---

### 4. Core Data Models (Pydantic – implement exactly)

Use the schemas above (LocationNode, Character, Event, Effect, ActionPool).  
Add these extra fields for runtime:

- `GameState`: current_round, active_location_ids, global_flags, etc.
- Every model must be serializable to/from JSON and to SQLite.

Seeds must be loadable from JSON files in `/seeds` with the same shape.

---

### 5. Database Design (SQLite MVP)

**Tables:**
- `locations` (id, name, description, tags, environment JSON, flags JSON, last_mutated_round)
- `location_connections` (from_id, to_id, type, travel_time, propagation_modifier)
- `characters` (id, name, type, location_id, stats JSON, inventory JSON, personality, goals, secrets, quickness, memory JSON, relationships JSON, …)
- `action_pools` (id, location_id, round, status, actions JSON)
- `events` / `effects` (for history & debugging)
- `game_sessions` (id, seed_name, current_round, state_snapshot JSON)

Graph is reconstructed into NetworkX on load / when needed.

---

### 6. LLM Provider Spec

```python
# llm/provider.py
class LLMProvider:
    def __init__(self, mode: Literal["qwen", "kobold"] = "qwen"):
        ...

    async def chat(self, messages, **kwargs) -> str:
        # Uses LiteLLM under the hood
```

- **Qwen**: via Dashscope / official Qwen API (or OpenRouter if preferred)
- **KoboldCPP**: point `api_base` to `http://localhost:5001/v1` (or configurable) and use any model name

Configuration via `.env` + `config.py`.

---

### 7. Development Phases (for the coding agent)

**Phase 0 – Skeleton (1–2 days)**
- Project setup, Pydantic models, SQLite schema, basic repository
- JSON seed loader
- LiteLLM wrapper that can talk to both Qwen and Kobold
- Empty LangGraph placeholder

**Phase 1 – Core Simulation (no LLM yet)**
- Location graph with NetworkX
- Action Pool creation & locking
- Reaction Score calculation + NPC ordering
- Eligibility logic
- Effect applier
- Hard-coded / rule-based “DM” that can resolve simple pools
- CLI that can run rounds with mocked actions

**Phase 2 – Real DM Agent**
- LangGraph graph for the Round lifecycle
- DM Agent node that receives Action Pool + state and returns Effects + narrative
- Prompt engineering for consistent structured output (Effects + narration)
- Player free-text action → added to pool

**Phase 3 – Full MVP Playable**
- Load the “village on fire” seed
- 3 locations + 4 NPCs working end-to-end
- Save / load session
- Background location simulation (even if player is not there)
- Basic CLI interface that feels like a playable game

**Phase 4 – Content Pipeline**
- Make seeds fully data-driven (JSON)
- Validation of seed files
- Prepare structure so a future UI can create/edit locations, NPCs, PCs, and world seeds

**Phase 5+ (later)**
- Better NPC agency (optional dedicated NPC agents)
- More sophisticated conflict resolution
- UI (web or otherwise)
- Switch SQLite → Postgres
- Optional real graph DB if needed

---

### 8. Key Implementation Rules for the Coding Agent

1. **All permanent state changes must go through Effects**. Never mutate state directly in agents.
2. Action Pools are **location-scoped**.
3. PCs always declare after all NPCs in a scope.
4. Use structured output (Pydantic / JSON mode) from the DM whenever possible.
5. Keep the DM prompt versioned and in `/agents/prompts/`.
6. Every round must be deterministic given the same seed + player inputs + random seed (for reaction score variance).
7. Design every model and repository method so content can later be created via JSON or UI without code changes.

---

### 9. First Concrete Deliverable

The coding agent should start by producing:

1. Full project skeleton + `pyproject.toml`
2. All Pydantic models
3. SQLite schema + basic repository
4. JSON seed format + the “village_fire” seed
5. Working LiteLLM provider (Qwen + Kobold)
6. A simple CLI that can load a seed and print the starting state

Once that is solid, move to the simulation engine.

---

