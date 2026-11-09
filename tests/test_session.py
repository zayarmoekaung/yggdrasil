"""Tests for session save/load."""

import json
import tempfile
from pathlib import Path

import pytest

from aetherdm.db.repository import Repository
from aetherdm.models import Character, GameState, LocationNode
from aetherdm.session import SessionManager


@pytest.fixture()
def repo(tmp_path: Path):
    db_path = tmp_path / "test.db"
    r = Repository(db_path)
    r.connect()
    yield r
    r.close()


@pytest.fixture()
def session_manager(repo: Repository):
    return SessionManager(repo)


@pytest.fixture()
def sample_game_state():
    return GameState(
        session_id="session-test",
        seed_name="village_fire",
        current_round=3,
        active_location_ids=["town", "forest"],
        global_flags={"crisis_active": True},
        world_history=["Round 1: Fire started", "Round 2: NPCs evacuated"],
    )


class TestSessionManager:
    def test_save_and_load_session(self, session_manager: SessionManager, sample_game_state: GameState):
        session_manager.save_session("my_session", sample_game_state)
        loaded = session_manager.load_session("my_session")
        assert loaded is not None
        assert loaded.session_id == "my_session"
        assert loaded.seed_name == "village_fire"
        assert loaded.current_round == 3
        assert loaded.global_flags["crisis_active"] is True

    def test_load_nonexistent_session(self, session_manager: SessionManager):
        loaded = session_manager.load_session("does_not_exist")
        assert loaded is None

    def test_overwrite_session(self, session_manager: SessionManager, sample_game_state: GameState):
        session_manager.save_session("my_session", sample_game_state)
        updated = GameState(
            session_id="my_session",
            seed_name="village_fire",
            current_round=10,
            active_location_ids=["town"],
            global_flags={},
            world_history=["updated"],
        )
        session_manager.save_session("my_session", updated)
        loaded = session_manager.load_session("my_session")
        assert loaded.current_round == 10
        assert loaded.global_flags == {}

    def test_list_sessions(self, session_manager: SessionManager, sample_game_state: GameState):
        session_manager.save_session("session1", sample_game_state)
        session_manager.save_session("session2", GameState(
            session_id="session2",
            seed_name="other_seed",
            current_round=1,
        ))
        sessions = session_manager.list_sessions()
        assert len(sessions) == 2
        names = {s["id"] for s in sessions}
        assert "session1" in names
        assert "session2" in names

    def test_list_sessions_empty(self, session_manager: SessionManager):
        assert session_manager.list_sessions() == []
