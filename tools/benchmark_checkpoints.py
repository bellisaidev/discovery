"""Milestone 4 verification: six sequential long runs, checkpoint timings and restore.

Run without other CPU/disk-heavy jobs. Both arms retain a regular-close checkpoint.
No numerical parameters are changed to make the population survive.
"""

import argparse
import gc
import hashlib
import json
import platform
import sqlite3
import statistics
import time
import uuid
from contextlib import closing
from pathlib import Path

import numpy as np

from digital_ecosystem.checkpoint import CheckpointManager, compatibility, resume
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.simulation import Simulation


def run_case(root, steps, automatic, index, config_path=None, population=None, parameters=None):
    config = (
        Configuration.from_dict(parameters)
        if parameters is not None
        else Configuration.load(config_path)
    )
    config.checkpoint.enabled = automatic
    if population is not None:
        config.world.initial_population = population
    output = root / f"case-{index}-auto{int(automatic)}-{uuid.uuid4().hex[:8]}"
    gc.collect()
    started = time.perf_counter()
    simulation = Simulation(config, seed=42)
    logger = ExperimentLogger(simulation, output)
    manager = CheckpointManager(logger)
    for _ in range(steps):
        simulation.step()
        logger.observe()
        # Both arms record exactly the same tick boundaries, including the forced
        # observations needed by a checkpoint between ordinary 30-tick samples.
        if simulation.tick % config.checkpoint.interval_ticks == 0:
            logger.flush()
        manager.maybe_save()
    path = manager.save("close")
    summary = logger.close()
    elapsed = time.perf_counter() - started
    row = {
        "automatic": automatic,
        "steps": steps,
        "initial_population": config.world.initial_population,
        "preset": str(config_path or "experimental"),
        "seconds": elapsed,
        "engine_fingerprint": simulation.state_fingerprint(),
        "summary": summary,
        "checkpoint_measurements": manager.measurements,
        "final_checkpoint": str(path),
        "retained_versions": len(list(manager.directory.glob("*.dlcp"))),
        "database_bytes": logger.database.stat().st_size,
    }
    assert row["retained_versions"] <= 4
    # A self-contained restore has no need to open the working database.
    unavailable = logger.database.with_suffix(".unavailable")
    logger.database.rename(unavailable)
    try:
        restored, restored_logger = resume(path, output / "isolated-restore")
        assert restored.state_fingerprint() == row["engine_fingerprint"]
        simulation.step()
        restored.step()
        restored_logger.observe()
        assert simulation.state_fingerprint() == restored.state_fingerprint()
        restored_logger.close()
    finally:
        unavailable.rename(logger.database)
    with closing(sqlite3.connect(logger.database)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        columns = [
            column[1]
            for column in connection.execute("PRAGMA table_info(samples)")
            if column[1] != "experiment_id"
        ]
        samples = connection.execute(
            f"SELECT {','.join(columns)} FROM samples WHERE experiment_id=? ORDER BY tick",
            (logger.experiment_id,),
        ).fetchall()
        row["sample_count"] = len(samples)
        row["observations_sha256"] = hashlib.sha256(
            json.dumps(samples, separators=(",", ":")).encode()
        ).hexdigest()
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=100000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--root", type=Path, default=Path("experiments/m4-performance"))
    parser.add_argument("--output", type=Path, default=Path("docs/m4-performance.json"))
    parser.add_argument(
        "--extras", action="store_true", help="Also diagnostic 10000 ticks and 10/100/256 bodies"
    )
    args = parser.parse_args()
    if args.steps <= 0 or args.repeats < 3:
        parser.error("Use positive steps and at least three pairs")
    report = {
        "environment": compatibility(),
        "platform": platform.platform(),
        "numpy": np.__version__,
        "steps": args.steps,
        "pairs": args.repeats,
        "budget_percent": 10,
        "logging_protocol": (
            "30-tick samples plus identical forced 10000-tick boundaries in both arms"
        ),
        "runs": [],
        "extras": [],
        "configuration": Configuration.load().to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def persist():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for index in range(args.repeats):
        fingerprints = set()
        observations = set()
        for automatic in (False, True) if index % 2 == 0 else (True, False):
            row = run_case(
                args.root, args.steps, automatic, index, parameters=report["configuration"]
            )
            fingerprints.add(row["engine_fingerprint"])
            observations.add(row["observations_sha256"])
            report["runs"].append(row)
            persist()
            print(
                json.dumps(
                    {
                        "pair": index,
                        "automatic": automatic,
                        "seconds": row["seconds"],
                        "checkpoint_count": len(row["checkpoint_measurements"]),
                        "last_bytes": row["checkpoint_measurements"][-1]["bytes"],
                    }
                ),
                flush=True,
            )
        assert len(fingerprints) == 1
        assert len(observations) == 1
    baseline = statistics.median(row["seconds"] for row in report["runs"] if not row["automatic"])
    automatic = statistics.median(row["seconds"] for row in report["runs"] if row["automatic"])
    report["baseline_median_seconds"] = baseline
    report["automatic_median_seconds"] = automatic
    report["overhead_percent"] = (automatic / baseline - 1) * 100
    report["budget_passed"] = report["overhead_percent"] <= 10
    persist()
    if args.extras:
        report["extras"].append(
            run_case(args.root, 10000, True, "diagnostic", "configs/diagnostic.toml")
        )
        persist()
        for population in (10, 100, 256):
            # Brief tests with the same physical model; no population rescue or free-action patch.
            row = run_case(args.root, 100, True, f"population{population}", population=population)
            report["extras"].append(row)
            persist()
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "baseline_median_seconds",
                    "automatic_median_seconds",
                    "overhead_percent",
                    "budget_passed",
                )
            }
        ),
        flush=True,
    )
    if not report["budget_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
