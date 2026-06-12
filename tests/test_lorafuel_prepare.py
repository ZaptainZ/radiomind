"""LoRAFuel-1b: prepare-habits gating + consumption recording.

Deterministic — stub habit stores and refine functions, no LLM, no store.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from radiomind.core.types import Habit, MemoryStatus
from radiomind.training.data_gen import DataGenReport, habit_id
from radiomind.training.fuel import PrepareReport, count_live_habits, prepare_habits


class _StubHabits:
    """all_habits() view over a mutable list — refine_fn can append."""

    def __init__(self, habits):
        self.habits = habits

    def all_habits(self):
        return list(self.habits)


def _h(desc: str, status=MemoryStatus.CANDIDATE) -> Habit:
    return Habit(description=desc, status=status)


def _refiner_minting(stub: _StubHabits, per_call: int):
    calls: list[str] = []

    def refine(dom: str):
        calls.append(dom)
        new = [_h(f"habit-{dom}-{i}") for i in range(per_call)]
        stub.habits.extend(new)
        return SimpleNamespace(new_insights=new)

    refine.calls = calls
    return refine


# ---------------- 低燃料触发 ----------------

def test_low_fuel_triggers_and_stops_at_threshold():
    stub = _StubHabits([_h("seed")])
    refine = _refiner_minting(stub, per_call=2)
    rep = prepare_habits(stub, ["big", "mid", "small", "tiny"], refine, min_count=5)
    assert rep.triggered and rep.reached
    assert rep.before == 1 and rep.after == 5
    # 1 + 2 + 2 = 5 → stops after 2 domains, never touches the rest
    assert refine.calls == ["big", "mid"]
    assert rep.domains_refined == [("big", 2), ("mid", 2)]


def test_archived_habits_do_not_count_as_fuel():
    stub = _StubHabits([_h("dead", MemoryStatus.ARCHIVED)] * 6)
    assert count_live_habits(stub) == 0
    refine = _refiner_minting(stub, per_call=5)
    rep = prepare_habits(stub, ["d1"], refine, min_count=5)
    assert rep.triggered and rep.reached and rep.after == 5


# ---------------- 足够燃料不触发 ----------------

def test_sufficient_fuel_never_refines():
    stub = _StubHabits([_h(f"x{i}") for i in range(5)])
    refine = _refiner_minting(stub, per_call=99)
    rep = prepare_habits(stub, ["big"], refine, min_count=5)
    assert not rep.triggered and rep.reached
    assert refine.calls == []
    assert rep.before == rep.after == 5


# ---------------- 失败给出明确原因 ----------------

def test_exhausted_domains_reports_reason():
    stub = _StubHabits([])
    refine = _refiner_minting(stub, per_call=0)  # LLM yields nothing
    rep = prepare_habits(stub, ["a", "b"], refine, min_count=5)
    assert rep.triggered and not rep.reached
    assert "0/5" in rep.reason
    assert len(rep.domains_refined) == 2


def test_refine_exception_recorded_not_fatal():
    stub = _StubHabits([])

    def boom(dom):
        raise RuntimeError("llm down")

    rep = prepare_habits(stub, ["a"], boom, min_count=5)
    assert rep.triggered and not rep.reached
    assert rep.domains_refined == [("a", 0)]


def test_max_domains_bounds_cost():
    stub = _StubHabits([])
    refine = _refiner_minting(stub, per_call=0)
    prepare_habits(stub, [f"d{i}" for i in range(20)], refine,
                   min_count=5, max_domains=3)
    assert len(refine.calls) == 3


# ---------------- 消费记录 ----------------

def test_habit_id_stable_and_compact():
    a = habit_id(_h("the user prefers adapters"))
    assert a == habit_id(_h("the user prefers adapters"))
    assert a != habit_id(_h("something else"))
    assert len(a) == 12


def test_datagen_report_habit_ids_field_defaults_empty():
    r = DataGenReport(train_count=0, valid_count=0, dropped_pii=0,
                      dropped_dup=0, dropped_short=0, habits_used=0,
                      domains_used=0)
    assert r.habit_ids == []


def test_train_result_carries_habit_ids():
    from radiomind.training.lora import TrainResult
    r = TrainResult(success=True, adapter_path=Path("/x"))
    assert r.habit_ids == []
    r.habit_ids = ["abc123def456"]
    assert r.habit_ids == ["abc123def456"]


# ---------------- CLI 接线（源码守卫，与既有模式一致） ----------------

def test_cli_exposes_prepare_flag_and_wiring():
    src = (Path(__file__).resolve().parents[1]
           / "src" / "radiomind" / "cli" / "main.py").read_text()
    assert "--prepare-habits/--no-prepare-habits" in src
    assert "prepare_habits(" in src
    assert "habit_ids=" in src or "habit_ids=" in src or "report.habit_ids" in src


def test_mind_train_writes_meta_and_threads_ids():
    src = (Path(__file__).resolve().parents[1]
           / "src" / "radiomind" / "core" / "mind.py").read_text()
    assert "generate_training_data_with_report()" in src
    assert "train_meta.json" in src
    assert "result.habit_ids = list(report.habit_ids)" in src
