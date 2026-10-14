"""Controlled engine benchmarks; parameters here are not experimental presets.

Run: uv run python tools/benchmark.py --steps 180 --output docs/benchmark.json
Includes measured Python/NumPy traced allocations (not total process RSS),
signal buffer bytes, and a timings-only window with tracing disabled.
"""

import argparse
import gc
import json
import platform
import time
import tracemalloc
from pathlib import Path

import numpy as np

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation


def benchmark(population, enabled, steps):
    config = Configuration()
    config.world.initial_population = population
    config.world.max_population = population
    config.signals.enabled = enabled
    config.body.initial_energy = config.body.energy_capacity
    config.body.metabolism = 0.1
    config.body.movement_cost = config.body.rotation_cost = config.body.harvesting_cost = 0
    config.signals.emission_cost = 0
    config.reproduction.threshold = 1
    gc.collect()
    tracemalloc.start()
    simulation = Simulation(config, seed=42)
    for _ in range(35):
        simulation.step()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    signal_bytes = simulation.signals.memory_bytes() if simulation.signals else 0
    durations = []
    for _ in range(steps):
        started = time.perf_counter()
        simulation.step()
        durations.append(time.perf_counter() - started)
    assert len(simulation.world.organisms) == population
    assert abs(simulation.world.energy_balance_error()) < 1e-6
    return {
        "population": population,
        "signals": enabled,
        "measured_ticks": steps,
        "mean_ms_per_tick": float(np.mean(durations) * 1000),
        "p95_ms_per_tick": float(np.quantile(durations, 0.95) * 1000),
        "ticks_per_second": 1 / float(np.mean(durations)),
        "traced_current_bytes_after_warmup": current,
        "traced_peak_bytes_after_warmup": peak,
        "signal_numpy_buffer_bytes": signal_bytes,
        "per_emitter_reference_field_bytes": population
        * 2
        * config.signals.rows
        * config.signals.columns
        * 8,
        "energy_balance_error": simulation.world.energy_balance_error(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=180)
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark.json"))
    args = parser.parse_args()
    if args.steps <= 0:
        parser.error("Steps must be positive")
    results = []
    for population in (10, 100, 256):
        for enabled in (False, True):
            row = benchmark(population, enabled, args.steps)
            results.append(row)
            print(json.dumps(row), flush=True)
    report = {
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "method": "35 warmup ticks; tracing only during warmup; no logger or renderer; "
        "reproduction threshold 1, cheap actions and metabolism for fixed-population diagnostics.",
        "memory_limit": "Tracemalloc and NumPy buffers; excludes total process RSS and SDL.",
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
