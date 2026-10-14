"""Descriptive factorial controls across seeds; no adaptive parameter search."""

import copy
import csv
import json
from itertools import product
from pathlib import Path

import numpy as np

from .experiment_logger import ExperimentLogger
from .simulation import Simulation


def run_comparison(config, seeds: list[int], steps: int, output: Path) -> dict:
    if len(set(seeds)) < 2 or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ValueError("Comparisons require at least two distinct nonnegative seeds")
    if steps < 0:
        raise ValueError("Steps must be nonnegative")
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for plasticity, mutations, signaling in product((False, True), repeat=3):
        label = f"p{int(plasticity)}m{int(mutations)}s{int(signaling)}"
        for seed in seeds:
            parameters = copy.deepcopy(config)
            parameters.neural.plasticity = plasticity
            parameters.neural.mutations = mutations
            parameters.signals.enabled = signaling
            simulation = Simulation(parameters, seed)
            logger = ExperimentLogger(simulation, output)
            status = "completed"
            try:
                for _ in range(steps):
                    simulation.step()
                    logger.observe()
            except KeyboardInterrupt:
                status = "interrupted"
                raise
            except BaseException:
                status = "failed"
                raise
            finally:
                summary = logger.close(status)
            results.append(
                dict(summary, condition=label, seed=seed, experiment_id=logger.experiment_id)
            )
    metrics = (
        "population",
        "births",
        "deaths",
        "mean_energy",
        "mean_neurons",
        "mean_connections",
        "genetic_diversity",
        "lineages",
        "harvested_energy",
        "offspring_energy",
        "contacts",
        "signal0_emissions",
        "signal1_emissions",
    )
    aggregates = {}
    for label in sorted({row["condition"] for row in results}):
        rows = [row for row in results if row["condition"] == label]
        aggregates[label] = {
            metric: {
                "n": len(rows),
                "mean": float(np.mean([row[metric] for row in rows])),
                "sample_std": float(np.std([row[metric] for row in rows], ddof=1)),
                "min": float(min(row[metric] for row in rows)),
                "max": float(max(row[metric] for row in rows)),
            }
            for metric in metrics
        }
    report = {
        "seeds": seeds,
        "steps": steps,
        "conditions": aggregates,
        "interpretation": "Descriptive observations only; no causal or adaptive conclusion.",
        "paired_design": "Same seed and physical parameters in all eight conditions.",
    }
    (output / "comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (output / "comparison_runs.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(results[0]))
        writer.writeheader()
        writer.writerows(results)
    return report
