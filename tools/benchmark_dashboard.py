"""Real timings on a generated, explicitly synthetic SQLite stress dataset.

No existing experiment is modified. Fixture creation runs in another process and
is excluded from timing and memory measurements. Filesystem caches are not flushed.
"""

import argparse
import ctypes
import gc
import hashlib
import json
import os
import platform
import sqlite3
import statistics
import subprocess
import sys
import time
from pathlib import Path


def create(root, samples, events, individuals):
    from digital_ecosystem.configuration import Configuration
    from digital_ecosystem.experiment_logger import ExperimentLogger
    from digital_ecosystem.observations import dictionaries
    from digital_ecosystem.simulation import Simulation

    root.mkdir(parents=True, exist_ok=False)
    sim = Simulation(Configuration(), 42)
    logger = ExperimentLogger(sim, root)
    identifier = logger.experiment_id
    sample = dictionaries(logger.connection.execute("SELECT * FROM samples LIMIT 1"))[0]
    person = dictionaries(logger.connection.execute("SELECT * FROM individuals LIMIT 1"))[0]
    logger.close()
    connection = sqlite3.connect(logger.database)
    connection.execute(
        "UPDATE experiments SET status='benchmark_synthetic',software_json=?",
        (json.dumps({"synthetic_benchmark": True, "generator": Path(__file__).name}),),
    )
    connection.execute("DELETE FROM samples")
    connection.execute("DELETE FROM individuals")
    connection.execute("DELETE FROM birth_genomes")
    end = (samples - 1) * 30

    # Synthetic descriptive series: abrupt spikes exercise extrema retention.
    def sample_rows():
        for index in range(samples):
            row = dict(
                sample,
                tick=index * 30,
                simulated_time=index,
                population=180 if index == samples // 2 else 100 + index % 80,
                births=index,
                deaths=index // 2,
                mean_generation=index / 1000.0,
                max_generation=index // 800,
                mean_neurons=30 + index % 67,
                mean_connections=176 + index % 1325,
                genetic_diversity=(index % 1000) / 1000,
                distinct_genomes=20 + index % 100,
                lineages=10,
                harvested_energy=index * 4.0,
                dissipated_energy=index * 2.0,
                regenerated_energy=index * 3.0,
                total_energy=sample["total_energy"] + index,
                death_causes=json.dumps({"energy_exhaustion": index // 2}),
                generation_distribution=json.dumps({str(index // 800): 100 + index % 80}),
            )
            yield list(row.values())

    connection.executemany(
        f"INSERT INTO samples VALUES ({','.join('?' for _ in sample)})", sample_rows()
    )

    def people_rows():
        for identifier_number in range(1, individuals + 1):
            born = 0 if identifier_number <= 10 else identifier_number * 10
            death = None if identifier_number % 3 == 0 else min(end, born + 400)
            row = dict(
                person,
                id=identifier_number,
                parent_id=None if identifier_number <= 10 else identifier_number // 2,
                lineage_id=1 + (identifier_number % 10),
                generation=identifier_number.bit_length(),
                born_tick=born,
                death_tick=death,
                death_cause=None if death is None else "energy_exhaustion",
                lifespan=None if death is None else (death - born) * sim.config.world.dt,
                observed_age=((end if death is None else death) - born) * sim.config.world.dt,
            )
            yield list(row.values())

    connection.executemany(
        f"INSERT INTO individuals VALUES ({','.join('?' for _ in person)})", people_rows()
    )

    def event_rows():
        for sequence in range(1, events + 1):
            tick = sequence * end // max(1, events)
            yield (
                identifier,
                tick,
                "population_limit",
                1,
                json.dumps(
                    {
                        "tick": tick,
                        "kind": "population_limit",
                        "organism_id": 1,
                        "sequence": sequence,
                    }
                ),
                sequence,
            )

    connection.executemany(
        "INSERT INTO events(experiment_id,tick,kind,organism_id,details_json,event_seq) "
        "VALUES (?,?,?,?,?,?)",
        event_rows(),
    )
    connection.commit()
    counts = {
        table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("samples", "events", "individuals")
    }
    connection.close()
    info = {
        "database": str(logger.database),
        "experiment_id": identifier,
        "end_tick": end,
        "counts": counts,
        "synthetic": True,
        "description": "Independent stress records, not a simulated trajectory",
    }
    (root / "dataset.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info), flush=True)


def rss():
    if os.name == "nt":
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("faults", wintypes.DWORD),
                *[
                    (key, ctypes.c_size_t)
                    for key in (
                        "peak_working_set",
                        "working_set",
                        "peak_paged",
                        "paged",
                        "peak_nonpaged",
                        "nonpaged",
                        "pagefile",
                        "peak_pagefile",
                    )
                ],
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        api = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        api.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        api.restype = wintypes.BOOL
        if not api(wintypes.HANDLE(-1), ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.working_set, counters.peak_working_set
    path = Path("/proc/self/statm")
    if path.exists():
        return int(path.read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE"), None
    return None, None


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def measure(info, output):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import numpy as np
    import pygame

    from digital_ecosystem.analytics import (
        GROUPS,
        DataRequest,
        GenealogyTree,
        load_analytics,
        sample_values,
    )
    from digital_ecosystem.dashboard import DashboardRenderer
    from digital_ecosystem.observations import ExperimentReader

    database = Path(info["database"])
    original_hash = file_hash(database)
    renderer = DashboardRenderer(browse=database, experiment_id=info["experiment_id"])
    gc.collect()
    baseline_rss, _ = rss()
    report = {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pygame": pygame.version.ver,
        },
        "dataset": info,
        "method": "First SQLite view per group; filesystem cache warmed by integrity hashing, "
        "not flushed. "
        "Input timings include redraw of cached results; query latencies are separate.",
        "queries": [],
    }
    for group in GROUPS:
        request = DataRequest(
            str(database),
            info["experiment_id"],
            group,
            0,
            info["end_tick"],
            info["end_tick"],
            info["end_tick"],
            width=500,
        )
        renderer.group = group
        renderer.data = None
        renderer.range = (0, info["end_tick"])
        renderer.cursor = info["end_tick"]
        renderer.follow = False
        renderer.request_key = None
        renderer.request_time = 0
        started = time.perf_counter()
        deadline = started + 15
        while time.perf_counter() < deadline:
            renderer.draw()
            if renderer.data is not None and renderer.data["request"].group == group:
                break
            time.sleep(0.005)
        if renderer.data is None:
            raise RuntimeError(renderer.message or "Dashboard first view timed out")
        first_ms = (time.perf_counter() - started) * 1000
        data = renderer.data
        timings = []
        for _ in range(3):
            started = time.perf_counter()
            data = load_analytics(request)
            timings.append((time.perf_counter() - started) * 1000)
        renderer.group = group
        renderer.data = data
        renderer.range = (0, info["end_tick"])
        renderer.cursor = info["end_tick"]
        renderer.source_bounds = renderer.range
        renderer.follow = False
        renderer.request_key = ("benchmark-fixed-data",)
        durations = []
        for index in range(35):
            renderer.request_time = time.perf_counter()
            started = time.perf_counter()
            renderer.command("axis")
            renderer.draw()
            if index >= 5:
                durations.append((time.perf_counter() - started) * 1000)
        report["queries"].append(
            {
                "group": group,
                "first_view_ms": first_ms,
                "warm_median_ms": statistics.median(timings),
                "cached_input_and_redraw_p95_ms": float(np.quantile(durations, 0.95)),
                "retained_points": len(data["points"]),
                "source_samples": data["source_samples"],
            }
        )
    reader = ExperimentReader(database, experiment_id=info["experiment_id"])
    lookups = []
    for index in range(100):
        tick = index * info["end_tick"] // 100
        started = time.perf_counter()
        sample_values(reader, tick, ("population", "mean_generation"))
        lookups.append((time.perf_counter() - started) * 1000)
    report["original_sample_lookup_p95_ms"] = float(np.quantile(lookups, 0.95))
    tree = GenealogyTree(reader, info["end_tick"])
    for identifier in list(tree.nodes)[:10]:
        tree.toggle(identifier)
    report["genealogy_cached_nodes"] = len(tree.nodes)
    plans = reader.connection.execute(
        "EXPLAIN QUERY PLAN SELECT id FROM individuals WHERE experiment_id=? AND parent_id=? "
        "AND id>? ORDER BY id LIMIT 100",
        (info["experiment_id"], 1, 0),
    ).fetchall()
    report["genealogy_query_plan"] = plans
    current_rss, peak_rss = rss()
    report["observer_rss_increment_bytes"] = (
        current_rss - baseline_rss if current_rss is not None else None
    )
    report["observer_peak_rss_increment_bytes"] = (
        peak_rss - baseline_rss if peak_rss is not None else None
    )
    report["memory_method"] = (
        "OS process working set; peak minus pre-query working set. "
        "SDL initialized before baseline; fixture creation was a separate process."
    )
    report["budgets"] = {
        "first_view_2s": all(r["first_view_ms"] <= 2000 for r in report["queries"]),
        "cached_input_100ms_p95": all(
            r["cached_input_and_redraw_p95_ms"] <= 100 for r in report["queries"]
        ),
        "memory_64mib": report["observer_peak_rss_increment_bytes"] is not None
        and report["observer_peak_rss_increment_bytes"] <= 64 * 1024 * 1024,
    }
    reader.close()
    renderer.worker.close()
    renderer.archive_reader.close()
    renderer.library.close()
    pygame.quit()
    assert original_hash == file_hash(database), "Read-only benchmark modified scientific records"
    report["database_sha256_before_after"] = original_hash
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("experiments/m6-performance"))
    parser.add_argument("--output", type=Path, default=Path("docs/m6-performance.json"))
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--samples", type=int, default=100000)
    parser.add_argument("--events", type=int, default=1000000)
    parser.add_argument("--individuals", type=int, default=100000)
    args = parser.parse_args()
    if args.create:
        create(args.root, args.samples, args.events, args.individuals)
        return
    if not (args.root / "dataset.json").exists():
        subprocess.run(
            [
                sys.executable,
                str(Path(__file__)),
                "--create",
                "--root",
                str(args.root),
                "--samples",
                str(args.samples),
                "--events",
                str(args.events),
                "--individuals",
                str(args.individuals),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    info = json.loads((args.root / "dataset.json").read_text())
    measure(info, args.output)


if __name__ == "__main__":
    main()
