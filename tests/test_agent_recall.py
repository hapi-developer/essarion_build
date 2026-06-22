"""Cross-session recall — zero-dependency full-text search over saved sessions
(the agent's answer to "didn't we already do this?")."""

from __future__ import annotations

from pathlib import Path

import pytest

from essarion_build.agent._session import (
    Session,
    TaskTurn,
    save_session,
    search_sessions,
)


def _save(tmp: Path, sid: str, task: str, **turn_kw) -> None:
    s = Session(id=sid, cwd=str(tmp), provider="stub", model="test")
    s.history.append(TaskTurn(task=task, **turn_kw))
    save_session(s, sessions_dir=tmp)


def test_search_finds_matching_turn(tmp_path: Path) -> None:
    _save(tmp_path, "20260101-000000-aa", "harden the JWT validator against alg=none")
    hits = search_sessions("jwt alg none", sessions_dir=tmp_path, include_global=False)
    assert hits
    assert hits[0].session_id == "20260101-000000-aa"
    assert "jwt" in hits[0].snippet.lower()


def test_search_empty_query_returns_nothing(tmp_path: Path) -> None:
    _save(tmp_path, "s1", "anything")
    assert search_sessions("   ", sessions_dir=tmp_path, include_global=False) == []


def test_search_ranks_task_hits_above_body_hits(tmp_path: Path) -> None:
    _save(tmp_path, "s1", "add a caching layer", summary="touched redis")
    _save(tmp_path, "s2", "unrelated work", summary="caching caching caching mentioned")
    hits = search_sessions("caching", sessions_dir=tmp_path, include_global=False)
    assert [h.session_id for h in hits][:2] == ["s1", "s2"]


def test_search_respects_limit(tmp_path: Path) -> None:
    for i in range(5):
        _save(tmp_path, f"s{i}", f"task number {i} about widgets")
    hits = search_sessions("widgets", sessions_dir=tmp_path, limit=3, include_global=False)
    assert len(hits) == 3


# ---------- the recall tool ----------

@pytest.fixture
def project(tmp_path: Path) -> Path:
    from essarion_build.agent._tools import bind_tools, register_all

    (tmp_path / ".essarion").mkdir()
    bind_tools(tmp_path)
    register_all()
    return tmp_path


def test_recall_tool_finds_session(project: Path) -> None:
    from essarion_build.agent._project import find_project_root
    from essarion_build.agent._tools import recall

    sd = find_project_root(project).sessions_dir
    s = Session(id="20260101-000000-bb", cwd=str(project), provider="stub", model="test")
    s.history.append(TaskTurn(task="set up websocket reconnect logic"))
    save_session(s, sessions_dir=sd)
    out = recall("websocket reconnect")
    assert "websocket" in out.lower()
    assert "20260101-000000-bb" in out


def test_recall_tool_no_match(project: Path) -> None:
    from essarion_build.agent._tools import recall

    out = recall("zzz-nonexistent-term-qqq")
    assert "no past sessions" in out


def test_recall_tool_rejects_empty(project: Path) -> None:
    from essarion_build.agent._tools import recall

    with pytest.raises(ValueError):
        recall("   ")
