import re

import pytest

from app.agents.models import Agent, AgentSettings, Chunk
from app.agents.store import AgentNotFound, AgentStore, CapacityFull, PresetReadOnly

TTL = 100.0


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


CHUNKS = (Chunk("c-001", "제목", "본문입니다.", "제목\n본문입니다.", "text"),)


def _preset() -> Agent:
    return Agent(
        agent_id="preset-demo",
        name="데모",
        preset_id="demo",
        settings=AgentSettings(),
        chunks=CHUNKS,
        created_at=0.0,
        expires_at=None,
    )


def test_create_sets_id_and_times() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=clock)
    a = store.create("내 상담원", AgentSettings(), CHUNKS)
    assert re.fullmatch(r"ag_[0-9a-f]{12}", a.agent_id)
    assert a.preset_id is None
    assert a.created_at == 1000.0
    assert a.expires_at == 1000.0 + TTL
    assert store.get(a.agent_id) == a
    assert store.live_count() == 1


def test_get_missing_raises() -> None:
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=FakeClock())
    with pytest.raises(AgentNotFound):
        store.get("ag_000000000000")


def test_get_after_ttl_raises() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=clock)
    a = store.create("x", AgentSettings(), CHUNKS)
    clock.t += TTL - 1
    assert store.get(a.agent_id).agent_id == a.agent_id
    clock.t += 1
    with pytest.raises(AgentNotFound):
        store.get(a.agent_id)


def test_sweep_returns_expired_ids_only() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=clock)
    store.add_preset(_preset())
    old = store.create("old", AgentSettings(), CHUNKS)
    clock.t += 50
    new = store.create("new", AgentSettings(), CHUNKS)
    clock.t += 60
    assert store.sweep() == [old.agent_id]
    assert store.sweep() == []
    assert store.get(new.agent_id).name == "new"
    assert store.get("preset-demo").name == "데모"
    assert store.live_count() == 1


def test_capacity_full_and_sweep_frees_slot() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=2, clock=clock)
    store.add_preset(_preset())
    store.create("a", AgentSettings(), CHUNKS)
    store.create("b", AgentSettings(), CHUNKS)
    with pytest.raises(CapacityFull):
        store.create("c", AgentSettings(), CHUNKS)
    clock.t += TTL
    c = store.create("c", AgentSettings(), CHUNKS)
    assert store.live_count() == 1
    assert store.get(c.agent_id).name == "c"


def test_presets_not_counted_and_never_expire() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=1, clock=clock)
    store.add_preset(_preset())
    assert store.live_count() == 0
    clock.t += TTL * 1000
    assert store.get("preset-demo").expires_at is None
    store.create("a", AgentSettings(), CHUNKS)


def test_preset_update_and_delete_read_only() -> None:
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=FakeClock())
    store.add_preset(_preset())
    with pytest.raises(PresetReadOnly):
        store.update_settings("preset-demo", AgentSettings(tone="concise"))
    with pytest.raises(PresetReadOnly):
        store.delete("preset-demo")
    assert store.get("preset-demo").settings == AgentSettings()


def test_update_settings_replaces() -> None:
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=FakeClock())
    a = store.create("a", AgentSettings(), CHUNKS)
    new = AgentSettings(tone="concise", summary=True)
    b = store.update_settings(a.agent_id, new)
    assert b.settings == new
    assert b.agent_id == a.agent_id and b.chunks == a.chunks
    assert store.get(a.agent_id).settings == new


def test_delete_then_get_raises() -> None:
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=FakeClock())
    a = store.create("a", AgentSettings(), CHUNKS)
    store.delete(a.agent_id)
    assert store.live_count() == 0
    with pytest.raises(AgentNotFound):
        store.get(a.agent_id)
    with pytest.raises(AgentNotFound):
        store.delete(a.agent_id)
    with pytest.raises(AgentNotFound):
        store.update_settings(a.agent_id, AgentSettings())


def test_expired_update_raises_not_found() -> None:
    clock = FakeClock()
    store = AgentStore(ttl_s=TTL, max_agents=5, clock=clock)
    a = store.create("a", AgentSettings(), CHUNKS)
    clock.t += TTL
    with pytest.raises(AgentNotFound):
        store.update_settings(a.agent_id, AgentSettings())
