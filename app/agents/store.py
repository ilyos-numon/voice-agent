"""상담원 메모리 저장소 (만료·상한). 디스크에 쓰지 않는다."""

from __future__ import annotations

import dataclasses
import secrets
import threading
import time
from collections.abc import Callable

from app.agents.models import Agent, AgentSettings, Chunk


class AgentNotFound(LookupError): ...


class PresetReadOnly(PermissionError): ...


class CapacityFull(RuntimeError): ...


class AgentStore:
    def __init__(
        self, ttl_s: float, max_agents: int, clock: Callable[[], float] = time.time
    ) -> None:
        self._ttl_s = ttl_s
        self._max_agents = max_agents
        self._clock = clock
        self._lock = threading.Lock()
        self._presets: dict[str, Agent] = {}
        self._agents: dict[str, Agent] = {}

    def add_preset(self, agent: Agent) -> None:
        with self._lock:
            self._presets[agent.agent_id] = agent

    def create(self, name: str, settings: AgentSettings, chunks: tuple[Chunk, ...]) -> Agent:
        with self._lock:
            self._sweep_locked()
            if len(self._agents) >= self._max_agents:
                raise CapacityFull("상담원을 더 만들 수 없습니다")
            agent_id = "ag_" + secrets.token_hex(6)
            while agent_id in self._agents:
                agent_id = "ag_" + secrets.token_hex(6)
            now = self._clock()
            agent = Agent(
                agent_id=agent_id,
                name=name,
                preset_id=None,
                settings=settings,
                chunks=chunks,
                created_at=now,
                expires_at=now + self._ttl_s,
            )
            self._agents[agent_id] = agent
            return agent

    def get(self, agent_id: str) -> Agent:
        with self._lock:
            return self._get_locked(agent_id)

    def update_settings(self, agent_id: str, settings: AgentSettings) -> Agent:
        with self._lock:
            if agent_id in self._presets:
                raise PresetReadOnly(agent_id)
            agent = dataclasses.replace(self._get_locked(agent_id), settings=settings)
            self._agents[agent_id] = agent
            return agent

    def delete(self, agent_id: str) -> None:
        with self._lock:
            if agent_id in self._presets:
                raise PresetReadOnly(agent_id)
            self._get_locked(agent_id)
            del self._agents[agent_id]

    def sweep(self) -> list[str]:
        with self._lock:
            return self._sweep_locked()

    def live_count(self) -> int:
        with self._lock:
            return len(self._agents)

    def _expired(self, agent: Agent, now: float) -> bool:
        return agent.expires_at is not None and now >= agent.expires_at

    def _get_locked(self, agent_id: str) -> Agent:
        preset = self._presets.get(agent_id)
        if preset is not None:
            return preset
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        if self._expired(agent, self._clock()):
            del self._agents[agent_id]
            raise AgentNotFound(agent_id)
        return agent

    def _sweep_locked(self) -> list[str]:
        now = self._clock()
        gone = [aid for aid, a in self._agents.items() if self._expired(a, now)]
        for aid in gone:
            del self._agents[aid]
        return gone
