"""세션 질문 수 상한과 대기 순번이 있는 실행 관문."""

from __future__ import annotations

import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


class SessionNotFound(LookupError): ...


class QuestionLimit(RuntimeError): ...


class Busy(RuntimeError): ...


@dataclass
class Session:
    session_id: str
    agent_id: str
    used: int
    max_questions: int
    expires_at: float


class SessionBook:
    def __init__(
        self, max_questions: int, ttl_s: float, clock: Callable[[], float] = time.time
    ) -> None:
        self._max_questions = max_questions
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}

    def open(self, agent_id: str) -> Session:
        with self._lock:
            now = self._clock()
            for sid in [k for k, s in self._sessions.items() if now >= s.expires_at]:
                del self._sessions[sid]
            session_id = "s_" + secrets.token_hex(6)
            while session_id in self._sessions:
                session_id = "s_" + secrets.token_hex(6)
            session = Session(
                session_id=session_id,
                agent_id=agent_id,
                used=0,
                max_questions=self._max_questions,
                expires_at=now + self._ttl_s,
            )
            self._sessions[session_id] = session
            return session

    def consume(self, session_id: str, agent_id: str) -> int:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is None or s.agent_id != agent_id:
                raise SessionNotFound(session_id)
            if self._clock() >= s.expires_at:
                del self._sessions[session_id]
                raise SessionNotFound(session_id)
            if s.used >= s.max_questions:
                raise QuestionLimit(session_id)
            s.used += 1
            return s.max_questions - s.used

    def refund(self, session_id: str) -> None:
        with self._lock:
            s = self._sessions.get(session_id)
            if s is not None and s.used > 0:
                s.used -= 1


class Ticket:
    def __init__(self, gate: TurnGate) -> None:
        self._gate = gate
        self.queued_at: float = time.monotonic()

    def position(self) -> int:
        return self._gate._position(self)

    def wait(self, timeout_s: float) -> bool:
        return self._gate._wait(self, timeout_s)

    def release(self) -> None:
        self._gate._release(self)


class TurnGate:
    def __init__(self, concurrency: int, max_waiting: int) -> None:
        self._concurrency = concurrency
        self._max_waiting = max_waiting
        self._cond = threading.Condition()
        self._running: set[Ticket] = set()
        self._queue: deque[Ticket] = deque()

    @property
    def running(self) -> int:
        with self._cond:
            return len(self._running)

    @property
    def waiting(self) -> int:
        with self._cond:
            return len(self._queue)

    def enter(self, allow_overflow: bool = False) -> Ticket:
        with self._cond:
            if not allow_overflow and len(self._queue) >= self._max_waiting:
                raise Busy("대기열이 가득 찼습니다")
            ticket = Ticket(self)
            self._queue.append(ticket)
            self._promote_locked()
            return ticket

    def _promote_locked(self) -> None:
        moved = False
        while self._queue and len(self._running) < self._concurrency:
            self._running.add(self._queue.popleft())
            moved = True
        if moved:
            self._cond.notify_all()

    def _position(self, ticket: Ticket) -> int:
        with self._cond:
            if ticket in self._running:
                return 0
            try:
                return self._queue.index(ticket) + 1
            except ValueError:
                return 0

    def _wait(self, ticket: Ticket, timeout_s: float) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: ticket in self._running, timeout=timeout_s)

    def _release(self, ticket: Ticket) -> None:
        with self._cond:
            if ticket in self._running:
                self._running.discard(ticket)
            else:
                try:
                    self._queue.remove(ticket)
                except ValueError:
                    return
            self._promote_locked()
            self._cond.notify_all()
