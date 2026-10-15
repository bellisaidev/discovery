"""Independent historical fixtures; statistical expectations are not copied from queries."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time

import pytest

from digital_ecosystem.analytics import (
    GROUPS,
    AnalyticsWorker,
    DataRequest,
    Envelope,
    GenealogyTree,
    HistoricalReader,
    genealogy_page,
    load_analytics,
    longevity,
    nearest_sample,
    sample_bounds,
    sampled_series,
)
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.observations import ExperimentReader, ObservationWriter, dictionaries
from digital_ecosystem.simulation import Simulation


@pytest.fixture
def history(tmp_path):
    config = Configuration()
    config.world.initial_population = 2
    config.logging.sample_interval = 10
    simulation = Simulation(config)
    logger = ExperimentLogger(simulation, tmp_path)
    ObservationWriter(logger).capture(1)
    identifier = logger.experiment_id
    sample = dictionaries(logger.connection.execute("SELECT * FROM samples LIMIT 1"))[0]
    person = dictionaries(logger.connection.execute("SELECT * FROM individuals LIMIT 1"))[0]
    snapshot = logger.connection.execute("SELECT * FROM neural_snapshots LIMIT 1").fetchone()
    genome_id = snapshot[3]
    logger.close()
    connection = sqlite3.connect(logger.database)
    connection.execute("DELETE FROM samples")
    connection.execute("DELETE FROM individuals")
    connection.execute("DELETE FROM birth_genomes")
    for tick, pop, births, deaths, causes in (
        (0, 2, 0, 0, {}),
        (10, 1, 0, 1, {"energy_exhaustion": 1}),
        (20, 1, 1, 2, {"energy_exhaustion": 1, "age_limit": 1}),
        (30, 1, 1, 2, {"energy_exhaustion": 1, "age_limit": 1}),
        (60, 0, 2, 4, {"energy_exhaustion": 2, "age_limit": 2}),
    ):
        row = dict(
            sample,
            tick=tick,
            simulated_time=tick * config.world.dt,
            population=pop,
            births=births,
            deaths=deaths,
            harvested_energy=tick * 4.0,
            dissipated_energy=tick * 2.0,
            offspring_energy=tick * 99.0,
            death_causes=json.dumps(causes),
            mean_generation=1.0 if tick >= 20 and pop else 0.0,
            max_generation=1 if tick >= 20 and pop else 0,
            generation_distribution=json.dumps({"1" if tick >= 20 else "0": pop} if pop else {}),
        )
        connection.execute(
            f"INSERT INTO samples VALUES ({','.join('?' for _ in row)})", list(row.values())
        )
    for organism, born, death, parent, lineage, cause in (
        (1, 0, 10, None, 1, "energy_exhaustion"),
        (2, 0, 20, None, 2, "age_limit"),
        (3, 15, 60, 2, 2, "energy_exhaustion"),
        (4, 40, 50, 3, 2, "age_limit"),
    ):
        lifespan = (death - born) * config.world.dt
        row = dict(
            person,
            id=organism,
            born_tick=born,
            death_tick=death,
            parent_id=parent,
            lineage_id=lineage,
            generation=0 if parent is None else 1 if parent == 2 else 2,
            death_cause=cause,
            lifespan=lifespan,
            observed_age=lifespan,
            offspring=8,
            descendants=99,
        )
        connection.execute(
            f"INSERT INTO individuals VALUES ({','.join('?' for _ in row)})", list(row.values())
        )
        connection.execute(
            "INSERT INTO birth_genomes VALUES (?,?,?)", (identifier, organism, genome_id)
        )
    future = list(snapshot)
    future[1], future[2] = 4, 45
    connection.execute("INSERT INTO neural_snapshots VALUES (?,?,?,?,?,?,?,?)", future)
    connection.execute(
        "INSERT INTO interventions VALUES (?,?,?,?,?,?,?)",
        (identifier, "synthetic", 18, "fixture", "Synthetic marker", 1, '{"test":true}'),
    )
    connection.commit()
    connection.close()
    return logger.database, identifier, config.world.dt


def request(history, group="Popolazione", cursor=30, start=0):
    database, identifier, _ = history
    return DataRequest(str(database), identifier, group, start, 60, 60, cursor, width=8)


def test_historical_cursor_never_reveals_future_life_genome_or_snapshot(history):
    database, identifier, dt = history
    reader = ExperimentReader(database, experiment_id=identifier)
    scoped = HistoricalReader(reader, 30)
    assert reader.individual(3)["death_tick"] == 60
    assert reader.snapshot(4, 45) is not None
    row = scoped.individual(3)
    assert row["death_tick"] is None and row["lifespan"] is None and row["death_cause"] is None
    assert row["observed_age"] == 15 * dt
    assert "descendants" not in row and "offspring" not in row
    assert scoped.individual(4) is None and scoped.genome(4) is None
    assert scoped.snapshot(4, 45) is None and scoped.snapshots(4) == []
    assert scoped.genome(3) is not None
    assert [r["id"] for r in scoped.ancestors(3)] == [2]
    reader.close()


def test_lifespans_medians_and_censoring_use_actual_death_cutoff(history):
    database, identifier, dt = history
    reader = ExperimentReader(database, experiment_id=identifier)
    points, life = longevity(reader, 0, 30, dt, width=3)
    assert life["completed"] == 2
    assert life["mean"] == pytest.approx(15 * dt)
    assert life["median"] == pytest.approx(15 * dt)
    assert life["living_censored"] == 1
    assert life["living_mean_age"] == pytest.approx(15 * dt)
    assert sum(r["lifespan_count"] for r in points) == 2
    assert sum(r["count"] for r in life["histogram"]) == 2
    _, window = longevity(reader, 15, 30, dt)
    assert window["completed"] == 1 and window["mean"] == pytest.approx(20 * dt)
    _, empty = longevity(reader, 21, 30, dt)
    assert empty["completed"] == 0 and empty["mean"] is None and empty["median"] is None
    reader.close()


def test_longevity_bins_do_not_move_deaths_into_an_earlier_interval(history):
    database, identifier, dt = history
    reader = ExperimentReader(database, experiment_id=identifier)
    for end in (10, 11, 20, 30, 60):
        points, _ = longevity(reader, 0, end, dt, width=3)
        for point in points:
            values = [
                r[0]
                for r in reader.connection.execute(
                    "SELECT lifespan FROM individuals WHERE experiment_id=? AND death_tick>=? "
                    "AND death_tick<=?",
                    (identifier, point["start_tick"], point["tick"]),
                )
            ]
            assert point["lifespan_count"] == len(values)
            if values:
                assert point["lifespan_mean"] == pytest.approx(sum(values) / len(values))
    reader.close()


def test_rates_use_original_adjacent_samples_before_reduction_and_no_double_count(history):
    database, identifier, dt = history
    reader = ExperimentReader(database, experiment_id=identifier)
    points, count = sampled_series(reader, "Energia", 10, 60, 1, 60)
    assert count == 4
    assert all(p["harvest_rate"] == pytest.approx(4 / dt) for p in points)
    assert all(p["consumption_rate"] == pytest.approx(2 / dt) for p in points)
    assert nearest_sample(reader, 19)["tick"] == 10
    assert sample_bounds(reader) == (0, 60)
    reader.close()


def test_envelope_retains_real_extrema_endpoints_and_bounded_memory():
    envelope = Envelope(0, 9999, 10, ("population",))
    for tick in range(10000):
        value = 400 if tick == 4321 else -20 if tick == 4678 else 10
        envelope.add({"tick": tick, "population": value})
    rows = envelope.rows()
    assert rows[0]["tick"] == 0 and rows[-1]["tick"] == 9999
    assert {4321, 4678} <= {r["tick"] for r in rows}
    assert len(rows) <= 40 and len(envelope.buckets) == 10


def test_real_source_gaps_remain_separate_segments(history):
    database, identifier, _ = history
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM samples WHERE tick=20")
    connection.commit()
    connection.close()
    reader = ExperimentReader(database, experiment_id=identifier)
    points, _ = sampled_series(reader, "Popolazione", 0, 60, 50, 60, sample_interval=10)
    segments = {r["tick"]: r["segment"] for r in points}
    assert segments[30] != segments[10] and segments[60] != segments[30]
    reader.close()


@pytest.mark.parametrize("group", list(GROUPS))
def test_all_analytics_are_read_only_and_cursor_details_are_not_future(history, group):
    database, _, _ = history
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = load_analytics(request(history, group))
    assert result["sample"]["tick"] == 30
    assert result["generations"] == {"1": 1}
    assert result["causes"] == {"energy_exhaustion": 1, "age_limit": 1}
    assert result["extinction_tick"] is None
    assert len(result["interventions"]) == 1
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_extinction_is_observed_death_tick_and_counts_preserve_causes(history):
    result = load_analytics(request(history, "Eventi", cursor=60))
    assert result["extinction_tick"] == 60
    assert result["causes"] == {"energy_exhaustion": 2, "age_limit": 2}
    assert result["sample"]["births"] == 2  # Founders were not counted as births.


def test_genealogy_progressive_expansion_collapse_pagination_and_cutoff(history):
    database, identifier, _ = history
    reader = ExperimentReader(database, experiment_id=identifier)
    tree = GenealogyTree(reader, 30)
    assert [r["id"] for r in tree.rows()] == [1, 2]
    tree.toggle(2)
    assert [(r["id"], r["depth"]) for r in tree.rows()] == [(1, 0), (2, 0), (3, 1)]
    assert tree.nodes[3]["death_tick"] is None
    tree.toggle(3)
    assert 4 not in tree.nodes
    tree.toggle(2)
    assert [r["id"] for r in tree.rows()] == [1, 2]
    assert [r["id"] for r in genealogy_page(reader, 60, parent=2, after=2, limit=1)] == [3]
    assert [r["id"] for r in genealogy_page(reader, 60, lineage=2)] == [2]
    reader.close()


def test_async_worker_only_publishes_latest_selection(history):
    worker = AnalyticsWorker()
    worker.request(request(history, "Energia"))
    worker.request(request(history, "Reti"))
    try:
        deadline = time.perf_counter() + 5
        while time.perf_counter() < deadline:
            result = worker.poll()
            if result:
                assert result[1] is None
                assert result[0]["request"].group == "Reti"
                break
            time.sleep(0.005)
        else:
            pytest.fail("Latest analytics request was not published")
    finally:
        worker.close()


def test_live_uncommitted_tail_is_visible_without_forcing_statistics_or_commit(tmp_path):
    config = Configuration()
    config.logging.sample_interval = 1
    config.logging.batch_samples = 100
    sim = Simulation(config)
    logger = ExperimentLogger(sim, tmp_path)
    for _ in range(3):
        sim.step()
        logger.observe()
    before = sim.state_fingerprint()
    reader = ExperimentReader(
        logger.database, connection=logger.connection, experiment_id=logger.experiment_id
    )
    assert reader.connection.in_transaction
    assert reader.connection.execute("SELECT tick FROM experiment_heads").fetchone()[0] == 0
    overlay = tuple(reader.samples(after=0))
    result = load_analytics(
        DataRequest(
            str(logger.database), logger.experiment_id, "Popolazione", 0, 3, 0, 3, 50, overlay
        )
    )
    assert result["sample"]["tick"] == 3 and result["source_samples"] == 4
    assert reader.connection.in_transaction
    assert reader.connection.execute("SELECT tick FROM experiment_heads").fetchone()[0] == 0
    assert before == sim.state_fingerprint()
    logger.close()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--headless"],
        ["--seed", "42"],
        ["--config", "configs/diagnostic.toml"],
        ["--resume", "not-used.dlcp"],
        ["--steps", "0"],
        ["--no-plasticity"],
        ["--export-csv"],
    ],
)
def test_browse_rejects_simulation_arguments_before_creating_output(history, arguments):
    database, _, _ = history
    result = subprocess.run(
        [sys.executable, "-m", "digital_ecosystem", "--browse", str(database), *arguments],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2 and "rejects" in result.stderr


def test_browse_cli_does_not_construct_a_simulation_and_does_not_write(history):
    database, identifier, _ = history
    before = database.read_bytes()
    script = """
import sys
from digital_ecosystem.simulation import Simulation
def forbidden(*args,**kwargs): raise AssertionError('Browser constructed a simulation')
Simulation.__init__=forbidden
from digital_ecosystem.__main__ import main
assert main(['--browse',sys.argv[1],'--experiment',sys.argv[2],'--gui-frames','3'])==0
from digital_ecosystem.dashboard import DashboardRenderer
r=DashboardRenderer(browse=sys.argv[1],experiment_id=sys.argv[2])
r.selected=3; r.cursor=60; r.follow=False; r.command('network'); r.draw()
assert r.inspector.cached_data is not None
assert r.inspector.cached_data.organism_id==3
# Moving before this individual's birth must invalidate the detached cache.
r.cursor=10; r.draw()
assert r.inspector.cached_data is None
r.run(max_frames=1)
"""
    subprocess.run(
        [sys.executable, "-c", script, str(database), identifier],
        env=dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy"),
        capture_output=True,
        text=True,
        check=True,
    )
    assert database.read_bytes() == before


def test_integrated_dashboard_navigation_and_archive_cannot_advance_current(history, tmp_path):
    database, identifier, _ = history
    script = """
import sys,time,pygame
from pathlib import Path
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.observations import ExperimentReader,ObservationWriter
from digital_ecosystem.dashboard import DashboardRenderer
s=Simulation(seed=3); l=ExperimentLogger(s,Path(sys.argv[3]))
r=DashboardRenderer(s,on_reader=lambda:ExperimentReader(l.database,connection=l.connection,
                    experiment_id=l.experiment_id),on_capture=ObservationWriter(l).capture)
r.draw(); before=s.state_fingerprint()
r.open_database(sys.argv[1],sys.argv[2]); assert r.paused and r.archive_active
r.command('play'); r.command('tick'); r.command('inspect_capture')
assert s.tick==0 and s.state_fingerprint()==before
r.command('group:Genealogia'); r.draw(); r.tree.toggle(2); r.genealogy=r.tree.rows(); r.draw()
r.selected=3; r.command('network'); r.draw()
r.command('dashboard'); r.command('group:Eventi')
deadline=time.perf_counter()+5
while r.data is None and time.perf_counter()<deadline: r.draw(); time.sleep(.01)
assert r.data is not None
r.command('axis'); r.command('reset_range'); r.draw()
assert r.seconds
r.command('current'); assert r.paused and not r.archive_active
assert s.state_fingerprint()==before
r.run(max_frames=2); l.close()
"""
    subprocess.run(
        [sys.executable, "-c", script, str(database), identifier, str(tmp_path / "live")],
        env=dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy"),
        capture_output=True,
        text=True,
        check=True,
    )
