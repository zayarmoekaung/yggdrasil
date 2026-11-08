-- AetherDM SQLite Schema
-- MVP schema — all JSON columns stored as TEXT, parsed by Pydantic on load.

CREATE TABLE IF NOT EXISTS locations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    environment TEXT DEFAULT '{}',
    flags TEXT DEFAULT '{}',
    last_mutated_round INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS location_connections (
    from_id TEXT NOT NULL REFERENCES locations(id),
    to_id TEXT NOT NULL REFERENCES locations(id),
    type TEXT NOT NULL,
    travel_time INTEGER DEFAULT 1,
    propagation_modifier REAL DEFAULT 1.0,
    PRIMARY KEY (from_id, to_id)
);

CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    location_id TEXT NOT NULL REFERENCES locations(id),
    stats TEXT DEFAULT '{}',
    inventory TEXT DEFAULT '[]',
    personality TEXT DEFAULT '',
    goals TEXT DEFAULT '[]',
    secrets TEXT DEFAULT '[]',
    quickness INTEGER DEFAULT 5,
    memory TEXT DEFAULT '[]',
    relationships TEXT DEFAULT '{}',
    conditions TEXT DEFAULT '[]',
    last_action_round INTEGER DEFAULT 0,
    current_plan TEXT
);

CREATE TABLE IF NOT EXISTS action_pools (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id TEXT NOT NULL REFERENCES locations(id),
    round INTEGER NOT NULL,
    status TEXT DEFAULT 'open',
    actions TEXT DEFAULT '[]',
    UNIQUE(location_id, round)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    round INTEGER NOT NULL,
    time_token INTEGER DEFAULT 0,
    origin_location_id TEXT NOT NULL REFERENCES locations(id),
    actor_id TEXT NOT NULL,
    type TEXT NOT NULL,
    intent TEXT DEFAULT '',
    intensity REAL DEFAULT 1.0,
    scope TEXT NOT NULL,
    remaining_intensity REAL DEFAULT 1.0,
    mechanical TEXT,
    visibility TEXT DEFAULT 'public'
);

CREATE TABLE IF NOT EXISTS effects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(id),
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    changes TEXT DEFAULT '{}',
    description TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS game_sessions (
    id TEXT PRIMARY KEY,
    seed_name TEXT NOT NULL,
    current_round INTEGER DEFAULT 0,
    state_snapshot TEXT DEFAULT '{}'
);
