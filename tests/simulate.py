"""Simulate a room with a TV02-like TRV: offset-only correction vs the PI controller.

Run:  python tests/simulate.py
"""

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "controller", Path(__file__).parents[1] / "custom_components/smart_trv/controller.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["controller"] = _mod
_spec.loader.exec_module(_mod)
PIController = _mod.PIController

TARGET = 22.0
OUTDOOR = 5.0
STEP = 0.5


def snap(x):
    return round(x / STEP) * STEP


def simulate(strategy, hours=24, start=18.0):
    room, rad = start, 0.0
    pi = PIController(kp=3.0, ki=1.0, max_boost=6.0, max_cut=3.0, step=STEP)
    trv_local = room + 0.5
    pi.seed(trv_local, room)
    setpoint = TARGET
    history = []
    for minute in range(hours * 60):
        trv_local = room + 0.5 + 2.5 * rad  # TRV sits next to the hot radiator
        if minute % 5 == 0:
            if strategy == "bt":
                setpoint = snap(TARGET + (trv_local - room))
            else:
                setpoint = pi.update(TARGET, round(room, 1), 5 / 60 if minute else 0, trv_local)
        valve = max(0.0, min(1.0, (setpoint - trv_local) / 0.5))
        rad += (valve - rad) / 10  # radiator warms/cools with ~10 min lag
        room += (6.0 * rad - 0.3 * (room - OUTDOOR)) / 60
        history.append((minute, room, setpoint))
    return history


def report(name, hist):
    last = [r for m, r, _ in hist if m >= 18 * 60]
    peak = max(r for _, r, _ in hist)
    reach = next((m for m, r, _ in hist if r >= TARGET - 0.1), None)
    print(f"{name:<22} last 6h avg {sum(last)/len(last):.2f} °C  "
          f"min/max {min(last):.2f}/{max(last):.2f}  peak {peak:.2f}  "
          f"within 0.1 °C after {reach if reach is None else f'{reach/60:.1f} h'}")
    return sum(last) / len(last), peak


if __name__ == "__main__":
    print(f"Target {TARGET} °C, TRV step {STEP} °C\n")
    bt_avg, _ = report("Offset only (P)", simulate("bt"))
    pi_avg, pi_peak = report("Smart TRV (PI)", simulate("pi"))
    assert bt_avg < TARGET - 0.3, "model should reproduce the offset-only steady-state error"
    assert abs(pi_avg - TARGET) < 0.15, "PI should settle on target"
    assert pi_peak < TARGET + 0.6, "PI should not overshoot much"
    print("\nOK")
