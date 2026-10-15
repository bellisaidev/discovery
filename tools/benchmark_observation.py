"""Sequential M4/current comparisons and measured observer/rendering costs.

The baseline source directory must be frozen before changing the repository.
No numerical parameters are modified in the long-run comparison.
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path


def worker(args):
    frozen = args.root / "frozen-src"
    if args.index.endswith("-current") and frozen.is_dir():
        sys.path.insert(0, str(frozen.resolve()))
    from benchmark_checkpoints import run_case

    result = run_case(
        args.root, args.steps, True, args.index, parameters=json.loads(args.parameters.read_text())
    )
    print(json.dumps(result), flush=True)


def rendering(root, output):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import numpy as np
    import pygame

    from digital_ecosystem.brain import Brain
    from digital_ecosystem.configuration import Configuration
    from digital_ecosystem.experiment_logger import ExperimentLogger
    from digital_ecosystem.genome import Connection, Genome, Node
    from digital_ecosystem.observations import ObservationWriter, capture_neural
    from digital_ecosystem.renderer import Renderer
    from digital_ecosystem.simulation import Simulation

    rows = []
    for population in (10, 100, 256):
        config = Configuration()
        config.world.initial_population = population
        sim = Simulation(config, 42)
        logger = ExperimentLogger(sim, root / f"capture-{population}")
        durations = []
        for _ in range(12):
            sim.step()
            logger.observe()
            started = time.perf_counter()
            ObservationWriter(logger).capture(1)
            durations.append((time.perf_counter() - started) * 1000)
        rows.append(
            {"population": population, "capture_p95_ms": float(np.quantile(durations, 0.95))}
        )
        logger.close()

    sim = Simulation(Configuration(), 42)
    nodes = {i: Node(i, "input" if i < 16 else "output" if i < 22 else "hidden") for i in range(96)}
    order = list(range(16)) + list(range(22, 96)) + list(range(16, 22))
    edges = [
        Connection(a, b, float(np.sin(a + b)))
        for j, a in enumerate(order)
        for b in order[j + 1 :]
        if nodes[a].kind != "output" and nodes[b].kind != "input"
    ]
    # Synthetic maximum-size graph, used only to measure the inspector.
    genome = Genome(nodes, edges[:1500], 96)
    genome.validate(sim.config.neural)
    sim.world.organisms[1].genome = genome
    sim.world.organisms[1].brain = Brain(genome, sim.config.neural)
    renderer = Renderer(sim)
    renderer.selected = 1
    renderer.view = "inspector"
    snapshot = capture_neural(sim, 1)
    before = sim.state_fingerprint()
    durations = []
    for i in range(100):
        renderer.inspector.cached_key = None  # Include detached capture on each draw.
        started = time.perf_counter()
        renderer.draw()
        if i >= 10:
            durations.append((time.perf_counter() - started) * 1000)
    assert before == sim.state_fingerprint()
    pygame.image.save(renderer.screen, str(output.parent / "m5-max-network.png"))
    dynamic_durations = []
    organism = sim.world.organisms[1]
    original = organism.brain.acquired.copy()
    for i in range(100):
        # Explicit synthetic visual stress: all acquired weights vary. This is
        # not a simulation trajectory or an invocation of an altered learner.
        organism.brain.acquired[:] = np.sin(np.arange(1500) + i * 0.01) * 0.1
        renderer.inspector.cached_key = None
        started = time.perf_counter()
        renderer.draw()
        if i >= 10:
            dynamic_durations.append((time.perf_counter() - started) * 1000)
    organism.brain.acquired[:] = original
    assert before == sim.state_fingerprint()
    result = {
        "capture": rows,
        "graph_nodes": len(snapshot.genome["nodes"]),
        "graph_edges": len(snapshot.genome["connections"]),
        "sdl_driver": pygame.display.get_driver(),
        "inspector_total_draw_p95_ms": float(np.quantile(durations, 0.95)),
        "inspector_total_draw_median_ms": statistics.median(durations),
        "inspector_changing_weights_draw_p95_ms": float(np.quantile(dynamic_durations, 0.95)),
        "changing_weights_method": "Synthetic maximum graph; every acquired weight changes "
        "each frame, outside the simulation. Numeric values retain full precision.",
        "capture_samples_per_population": 12,
        "warmup_frames": 10,
        "measured_frames_per_graph_scenario": 90,
    }
    result["budgets"] = {
        "capture_250ms_p95": all(row["capture_p95_ms"] <= 250 for row in rows),
        "static_graph_10ms_p95": result["inspector_total_draw_p95_ms"] <= 10,
        "changing_graph_10ms_p95": result["inspector_changing_weights_draw_p95_ms"] <= 10,
    }
    pygame.quit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--steps", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--root", type=Path, default=Path("experiments/m5-performance"))
    parser.add_argument("--output", type=Path, default=Path("docs/m5-performance.json"))
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--parameters", type=Path)
    parser.add_argument("--index", default="0")
    parser.add_argument("--render-only", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    from digital_ecosystem.checkpoint import compatibility
    from digital_ecosystem.configuration import Configuration

    args.root.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    config = Configuration.load().to_dict()
    parameters = args.root / "parameters.json"
    parameters.write_text(json.dumps(config), encoding="utf-8")
    report = {
        "environment": compatibility(),
        "configuration": config,
        "steps": args.steps,
        "runs": [],
    }

    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not args.render_only:
        if not args.baseline or args.repeats < 3:
            parser.error("Provide --baseline frozen-source-directory and at least three repeats")
        for pair in range(args.repeats):
            for baseline in (True, False) if pair % 2 == 0 else (False, True):
                env = dict(os.environ)
                env["PYTHONPATH"] = str((args.baseline if baseline else Path("src")).resolve())
                command = [
                    sys.executable,
                    str(Path(__file__)),
                    "--worker",
                    "--steps",
                    str(args.steps),
                    "--root",
                    str(args.root),
                    "--parameters",
                    str(parameters),
                    "--index",
                    f"{pair}-{'m4' if baseline else 'current'}",
                ]
                process = subprocess.run(
                    command, env=env, capture_output=True, text=True, check=True
                )
                row = json.loads(process.stdout.strip().splitlines()[-1])
                row.update(pair=pair, baseline=baseline)
                report["runs"].append(row)
                print(
                    json.dumps({"pair": pair, "baseline": baseline, "seconds": row["seconds"]}),
                    flush=True,
                )
                save()
        for pair in range(args.repeats):
            rows = [r for r in report["runs"] if r["pair"] == pair]
            assert rows[0]["engine_fingerprint"] == rows[1]["engine_fingerprint"]
            assert rows[0]["observations_sha256"] == rows[1]["observations_sha256"]
        medians = {
            str(b): statistics.median(r["seconds"] for r in report["runs"] if r["baseline"] == b)
            for b in (True, False)
        }
        report["medians_seconds"] = medians
        report["overhead_percent"] = 100 * (medians["False"] / medians["True"] - 1)
        report["headless_budget_passed"] = report["overhead_percent"] <= 10
    report["rendering"] = rendering(args.root, args.output)
    save()
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"runs", "environment", "configuration"}}
        )
    )


if __name__ == "__main__":
    main()
