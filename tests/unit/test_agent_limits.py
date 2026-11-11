import re
import threading

import pytest

from app.agents.limits import (
    Busy,
    QuestionLimit,
    SessionBook,
    SessionNotFound,
    TurnGate,
)


class FakeClock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---- SessionBook ----


def test_open_session_fields() -> None:
    book = SessionBook(max_questions=30, ttl_s=100.0, clock=FakeClock())
    s = book.open("ag_1")
    assert re.fullmatch(r"s_[0-9a-f]{12}", s.session_id)
    assert (s.agent_id, s.used, s.max_questions, s.expires_at) == ("ag_1", 0, 30, 1100.0)


def test_consume_30_then_limit() -> None:
    book = SessionBook(max_questions=30, ttl_s=100.0, clock=FakeClock())
    s = book.open("ag_1")
    left = [book.consume(s.session_id, "ag_1") for _ in range(30)]
    assert left[0] == 29
    assert left[-1] == 0
    with pytest.raises(QuestionLimit):
        book.consume(s.session_id, "ag_1")


def test_refund_gives_one_back() -> None:
    book = SessionBook(max_questions=2, ttl_s=100.0, clock=FakeClock())
    s = book.open("ag_1")
    assert book.consume(s.session_id, "ag_1") == 1
    assert book.consume(s.session_id, "ag_1") == 0
    book.refund(s.session_id)
    assert book.consume(s.session_id, "ag_1") == 0
    with pytest.raises(QuestionLimit):
        book.consume(s.session_id, "ag_1")


def test_refund_never_below_zero_and_unknown_safe() -> None:
    book = SessionBook(max_questions=2, ttl_s=100.0, clock=FakeClock())
    s = book.open("ag_1")
    book.refund(s.session_id)
    book.refund("s_missing")
    assert book.consume(s.session_id, "ag_1") == 1


def test_other_agent_session_not_found() -> None:
    book = SessionBook(max_questions=30, ttl_s=100.0, clock=FakeClock())
    s = book.open("ag_1")
    with pytest.raises(SessionNotFound):
        book.consume(s.session_id, "ag_2")
    with pytest.raises(SessionNotFound):
        book.consume("s_000000000000", "ag_1")
    assert book.consume(s.session_id, "ag_1") == 29


def test_expired_session_not_found() -> None:
    clock = FakeClock()
    book = SessionBook(max_questions=30, ttl_s=100.0, clock=clock)
    s = book.open("ag_1")
    clock.t += 100
    with pytest.raises(SessionNotFound):
        book.consume(s.session_id, "ag_1")


# ---- TurnGate ----


def test_positions_with_concurrency_2() -> None:
    gate = TurnGate(concurrency=2, max_waiting=8)
    t1, t2, t3, t4 = (gate.enter() for _ in range(4))
    assert [t.position() for t in (t1, t2, t3, t4)] == [0, 0, 1, 2]
    assert (gate.running, gate.waiting) == (2, 2)
    assert t1.wait(0) is True
    assert t3.wait(0.01) is False


def test_release_promotes_fifo() -> None:
    gate = TurnGate(concurrency=2, max_waiting=8)
    t1, _t2, t3, t4 = (gate.enter() for _ in range(4))
    t1.release()
    assert t3.position() == 0
    assert t4.position() == 1
    assert t3.wait(0) is True
    assert (gate.running, gate.waiting) == (2, 1)


def test_waiting_ticket_release_leaves_queue() -> None:
    gate = TurnGate(concurrency=1, max_waiting=8)
    t1, t2, t3 = (gate.enter() for _ in range(3))
    t2.release()
    assert t3.position() == 1
    assert gate.waiting == 1
    t1.release()
    assert t3.position() == 0


def test_busy_when_queue_full() -> None:
    gate = TurnGate(concurrency=1, max_waiting=2)
    gate.enter()
    gate.enter()
    gate.enter()
    with pytest.raises(Busy):
        gate.enter()
    assert gate.waiting == 2


def test_allow_overflow_never_busy() -> None:
    gate = TurnGate(concurrency=1, max_waiting=1)
    gate.enter()
    gate.enter()
    t = gate.enter(allow_overflow=True)
    assert t.position() == 2
    assert gate.waiting == 2


def test_release_twice_is_safe() -> None:
    gate = TurnGate(concurrency=1, max_waiting=8)
    t1 = gate.enter()
    t2 = gate.enter()
    t1.release()
    t1.release()
    assert (gate.running, gate.waiting) == (1, 0)
    assert t2.position() == 0
    t2.release()
    t2.release()
    assert (gate.running, gate.waiting) == (0, 0)


def test_wait_wakes_on_release_from_other_thread() -> None:
    gate = TurnGate(concurrency=1, max_waiting=8)
    t1 = gate.enter()
    t2 = gate.enter()
    timer = threading.Timer(0.05, t1.release)
    timer.start()
    assert t2.wait(2.0) is True
    timer.join()


def test_queued_at_is_set() -> None:
    gate = TurnGate(concurrency=1, max_waiting=8)
    t = gate.enter()
    assert isinstance(t.queued_at, float)


def test_ten_threads_enter_release() -> None:
    gate = TurnGate(concurrency=2, max_waiting=8)
    errors: list[BaseException] = []
    peak: list[int] = []
    lock = threading.Lock()
    start = threading.Barrier(10)

    def worker() -> None:
        try:
            start.wait()
            t = gate.enter()
            try:
                assert t.wait(5.0)
                with lock:
                    peak.append(gate.running)
            finally:
                t.release()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(10)
    assert errors == []
    assert len(peak) == 10
    assert max(peak) <= 2
    assert (gate.running, gate.waiting) == (0, 0)
