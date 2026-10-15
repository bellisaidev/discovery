import copy
import json
import shutil
import sqlite3
import zipfile
from contextlib import closing
from itertools import product
from pathlib import Path

import numpy as np
import pytest

from digital_ecosystem.checkpoint import CheckpointManager, compatibility, read_checkpoint, resume
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.neural_layout import graph_layout
from digital_ecosystem.observations import (
    ExperimentReader,
    InterventionRecord,
    ObservationWriter,
    capture_neural,
    genetic_difference,
)
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.state import fingerprint
from digital_ecosystem.storage import history_digest, observation_revision


def session(tmp_path, seed=42, config=None):
    simulation = Simulation(config or Configuration.load("configs/diagnostic.toml"), seed)
    logger = ExperimentLogger(simulation, tmp_path)
    return simulation, logger, ObservationWriter(logger)


def advance(simulation, logger, ticks):
    for _ in range(ticks):
        simulation.step()
        logger.observe()


def test_live_snapshot_is_detached_and_does_not_evaluate_or_learn(tmp_path, monkeypatch):
    s, logger, writer = session(tmp_path)
    advance(s, logger, 17)
    before = fingerprint(s.to_state())
    brain = s.world.organisms[1].brain

    def forbidden(*args):
        raise AssertionError("Observer evaluated the controller")

    monkeypatch.setattr(brain, "forward", forbidden)
    monkeypatch.setattr(brain, "learn", forbidden)
    snapshot = capture_neural(s, 1)
    snapshot.genome["nodes"][0][2] = 999
    assert fingerprint(s.to_state()) == before
    stored = writer.capture(1)
    reader = ExperimentReader(connection=logger.connection, experiment_id=logger.experiment_id)
    recovered = reader.snapshot(1, 17)
    assert recovered == stored
    assert fingerprint(s.to_state()) == before
    genetic, effective = recovered.weights(s.config.neural.parameter_bound)
    np.testing.assert_array_equal(effective, np.clip(genetic + brain.acquired, -4, 4))
    np.testing.assert_array_equal(recovered.activities, brain.activities)
    writer.capture(1)
    assert observation_revision(logger.connection, logger.experiment_id) == 1
    assert logger.last_sample == 0  # Manual capture did not force a statistics sample.
    logger.close()


def test_intervention_pages_preserve_every_record_at_the_same_tick(tmp_path):
    simulation, logger, _ = session(tmp_path)
    records = [
        (logger.experiment_id, f"fixture-{i:04}", 0, "synthetic", "test", 1, "{}")
        for i in range(1203)
    ]
    logger.connection.executemany("INSERT INTO interventions VALUES (?,?,?,?,?,?,?)", records)
    reader = ExperimentReader(connection=logger.connection, experiment_id=logger.experiment_id)
    found, after_tick, after_id = [], -1, ""
    while page := reader.interventions(0, 0, after_tick=after_tick, after_id=after_id):
        found.extend(row["id"] for row in page)
        after_tick, after_id = page[-1]["tick"], page[-1]["id"]
    assert found == [row[1] for row in records]
    assert reader.interventions(1, 20) == []
    assert simulation.tick == 0
    logger.close()


def test_snapshot_changes_checkpoint_even_in_pause_and_is_self_contained(tmp_path):
    s, logger, writer = session(tmp_path / "original")
    advance(s, logger, 17)
    manager = CheckpointManager(logger)
    first = manager.save()
    snapshot = writer.capture(1)
    second = manager.save()
    assert first != second
    assert manager.save() == second
    logger.close()
    restored, imported = resume(second, tmp_path / "isolated")
    reader = ExperimentReader(connection=imported.connection, experiment_id=imported.experiment_id)
    assert reader.snapshot(1, 17) == snapshot
    assert restored.state_fingerprint() == s.state_fingerprint()
    imported.close()


def test_observations_do_not_fork_and_merge_same_uuid(tmp_path):
    s, logger, writer = session(tmp_path)
    advance(s, logger, 17)
    manager = CheckpointManager(logger)
    old = manager.save()
    identifier = logger.experiment_id
    writer.capture(1)
    newer = manager.save()
    logger.close()
    s, logger = resume(old, tmp_path)
    assert logger.experiment_id == identifier
    assert ExperimentReader(connection=logger.connection, experiment_id=identifier).snapshot(1, 17)
    logger.close()
    s, logger = resume(newer, tmp_path)
    assert logger.experiment_id == identifier
    assert logger.connection.execute("SELECT count(*) FROM neural_snapshots").fetchone()[0] == 1
    logger.close()


def test_fork_never_imports_observations_from_original_future(tmp_path):
    s, logger, writer = session(tmp_path)
    advance(s, logger, 17)
    writer.capture(1)
    old = CheckpointManager(logger).save()
    original = logger.experiment_id
    advance(s, logger, 24)
    writer.capture(1)
    logger.close()
    branched, branch = resume(old, tmp_path)
    assert branch.experiment_id != original
    reader = ExperimentReader(connection=branch.connection, experiment_id=branch.experiment_id)
    assert [row["tick"] for row in reader.snapshots(1)] == [17]
    assert reader.snapshot(1, 17).experiment_id == branch.experiment_id
    assert reader.snapshot(1, 41) is None
    ObservationWriter(branch).capture(1)
    assert (
        branch.connection.execute(
            "SELECT count(*) FROM neural_snapshots WHERE experiment_id=?", (original,)
        ).fetchone()[0]
        == 2
    )
    assert branched.tick == 17
    branch.close()


def test_same_tick_divergent_trajectory_observations_are_isolated(tmp_path):
    s, logger, writer = session(tmp_path)
    advance(s, logger, 17)
    archive = CheckpointManager(logger).save()
    original = logger.experiment_id
    s.world.organisms[1].brain.acquired[0] += 0.001
    writer.capture(1)
    logger.close()
    _, branch = resume(archive, tmp_path)
    assert branch.experiment_id != original
    assert not ExperimentReader(
        connection=branch.connection, experiment_id=branch.experiment_id
    ).snapshots(1)
    branch.close()


def test_snapshot_sqlite_failure_retries_without_advancing(tmp_path):
    s, logger, writer = session(tmp_path)
    advance(s, logger, 3)
    before = fingerprint(s.to_state())
    logger.connection.execute(
        "CREATE TEMP TRIGGER fail BEFORE INSERT ON neural_snapshots "
        "BEGIN SELECT RAISE(FAIL,'capture unavailable'); END"
    )
    with pytest.raises(RuntimeError):
        writer.capture(1)
    assert fingerprint(s.to_state()) == before
    logger.connection.execute("DROP TRIGGER IF EXISTS fail")
    writer.capture(1)
    assert observation_revision(logger.connection, logger.experiment_id) == 1
    assert (
        len(
            ExperimentReader(
                connection=logger.connection, experiment_id=logger.experiment_id
            ).snapshots(1)
        )
        == 1
    )
    assert fingerprint(s.to_state()) == before
    logger.close()


def test_dead_individual_has_genome_and_only_recorded_dynamic_data(tmp_path):
    config = Configuration.load("configs/diagnostic.toml")
    config.body.max_age = config.world.dt * 2
    s, logger, writer = session(tmp_path, config=config)
    writer.capture(1)
    advance(s, logger, 2)
    logger.flush()
    reader = ExperimentReader(connection=logger.connection, experiment_id=logger.experiment_id)
    assert reader.genome(1).activities is None
    assert reader.snapshot(1, 0).phase == "not_evaluated"
    assert reader.snapshot(1, 2) is None
    with pytest.raises(ValueError, match="not alive"):
        writer.capture(1)
    logger.close()


def test_genetic_comparison_does_not_confuse_plasticity_with_mutations(tmp_path):
    s, logger, _ = session(tmp_path)
    advance(s, logger, 3)
    child = next(o for o in s.world.organisms.values() if o.parent_id)
    reader = ExperimentReader(connection=logger.connection, experiment_id=logger.experiment_id)
    observed = capture_neural(s, child.id)
    parent = reader.genome(child.parent_id)
    difference = genetic_difference(observed, parent)
    observed2 = copy.deepcopy(observed)
    object.__setattr__(observed2, "acquired", tuple(0.3 for _ in observed.acquired))
    assert genetic_difference(observed2, parent) == difference
    assert graph_layout(observed.genome) == graph_layout(observed.genome)
    assert set(graph_layout(observed.genome)) == {n[0] for n in observed.genome["nodes"]}
    logger.close()


def test_intervention_boundary_is_observational_only_and_portable(tmp_path):
    s, logger, writer = session(tmp_path / "original")
    before = fingerprint(s.to_state())
    record = InterventionRecord(
        "synthetic", logger.experiment_id, 0, "test", "Fixture", 1, {"a": 2}
    )
    writer.append_intervention(record)
    writer.append_intervention(record)
    assert fingerprint(s.to_state()) == before
    archive = CheckpointManager(logger).save()
    logger.close()
    _, copied = resume(archive, tmp_path / "copy")
    reader = ExperimentReader(connection=copied.connection, experiment_id=copied.experiment_id)
    assert len(reader.interventions()) == 1
    assert reader.interventions()[0]["label"] == "Fixture"
    copied.close()


def test_genuine_m4_fixture_loads_continues_and_keeps_uuid(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    expected = json.loads((fixtures / "m4-tick17.json").read_text())
    if expected["compatibility"] != compatibility():
        pytest.skip("M4 binary fixture requires its original numerical environment")
    archive = fixtures / "m4-tick17.dlcp"
    with zipfile.ZipFile(archive) as z:
        assert json.loads(z.read("manifest.json"))["format"] == 1
    simulation, logger = resume(archive, tmp_path)
    assert logger.experiment_id == expected["experiment_id"]
    assert fingerprint(simulation.to_state()) == expected["fingerprints"]["17"]
    logger.close()
    simulation, logger = resume(archive, tmp_path)
    assert logger.experiment_id == expected["experiment_id"]
    for tick in (41, 120):
        advance(simulation, logger, tick - simulation.tick)
        assert fingerprint(simulation.to_state()) == expected["fingerprints"][str(tick)]
    logger.close()


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("plasticity,mutations,signals", list(product((False, True), repeat=3)))
def test_observation_reproducibility_matrix(tmp_path, seed, plasticity, mutations, signals):
    config = Configuration.load("configs/diagnostic.toml")
    config.neural.plasticity, config.neural.mutations = plasticity, mutations
    config.signals.enabled = signals
    a, la, _ = session(tmp_path / "control", seed, config)
    b, lb, writer = session(tmp_path / "observed", seed, config)
    for tick in range(1, 121):
        advance(a, la, 1)
        advance(b, lb, 1)
        if tick in {17, 41, 120}:
            for identifier in list(b.world.organisms)[:3]:
                snapshot = writer.capture(identifier)
                graph_layout(snapshot.genome)
            assert fingerprint(a.to_state()) == fingerprint(b.to_state())
            archive = CheckpointManager(lb).save()
            # Align the forced checkpoint sample boundary in the control.
            la.flush()
            original = lb.experiment_id
            lb.close()
            b, lb = resume(archive, tmp_path / "observed")
            writer = ObservationWriter(lb)
            assert lb.experiment_id == original
            assert fingerprint(a.to_state()) == fingerprint(b.to_state())
    la.flush()
    lb.flush()
    # UUID and wall-clock metadata differ; every sample/event/individual must match.
    for table, order in (("samples", "tick"), ("events", "event_seq"), ("individuals", "id")):
        columns = [
            r[1]
            for r in la.connection.execute(f"PRAGMA table_info({table})")
            if r[1] not in {"experiment_id", "event_id"}
        ]
        query = f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"
        assert la.connection.execute(query).fetchall() == lb.connection.execute(query).fetchall()
    la.close()
    lb.close()


def test_reader_read_only_legacy_capabilities_pagination_and_history_digest(tmp_path):
    s, logger, writer = session(tmp_path)
    writer.capture(1)
    archive = CheckpointManager(logger).save()
    digest = history_digest(logger.connection, logger.experiment_id)
    with read_checkpoint(archive) as (_, _, database):
        with closing(sqlite3.connect(database)) as connection:
            assert digest == history_digest(connection, logger.experiment_id)
    logger.close()
    reader = ExperimentReader(logger.database, experiment_id=logger.experiment_id)
    assert len(reader.individuals(limit=2)) == 2
    assert reader.individuals(after=2, limit=1)[0]["id"] == 3
    with pytest.raises(sqlite3.OperationalError):
        reader.connection.execute("DELETE FROM samples")
    reader.close()


def test_partial_tick_capture_is_rejected(tmp_path):
    s, logger, writer = session(tmp_path)
    s.at_tick_boundary = False
    with pytest.raises(ValueError):
        writer.capture(1)
    with pytest.raises(ValueError):
        capture_neural(s, 1)
    s.at_tick_boundary = True
    logger.close()


def test_genuine_m4_operational_database_migrates_without_false_fork(tmp_path):
    fixtures = Path(__file__).parent / "fixtures"
    expected = json.loads((fixtures / "m4-tick17.json").read_text())
    if expected["compatibility"] != compatibility():
        pytest.skip("M4 binary fixture requires its original numerical environment")
    shutil.copyfile(fixtures / "m4-tick17.sqlite3", tmp_path / "lab.sqlite3")
    archive = fixtures / "m4-tick17.dlcp"
    sim, logger = resume(archive, tmp_path)
    assert logger.experiment_id == expected["experiment_id"]
    assert logger.connection.execute("PRAGMA user_version").fetchone()[0] == 3
    ObservationWriter(logger).capture(1)
    logger.close()
    sim, logger = resume(archive, tmp_path)
    assert logger.experiment_id == expected["experiment_id"]
    assert ExperimentReader(
        connection=logger.connection, experiment_id=logger.experiment_id
    ).snapshot(1, 17)
    advance(sim, logger, 103)
    assert fingerprint(sim.to_state()) == expected["fingerprints"]["120"]
    assert logger.connection.execute("SELECT count(*) FROM experiments").fetchone()[0] == 1
    logger.close()


def test_operational_m4_migration_rollback_backup_and_logical_history(tmp_path, monkeypatch):
    from digital_ecosystem import storage

    fixtures = Path(__file__).parent / "fixtures"
    database = tmp_path / "lab.sqlite3"
    shutil.copyfile(fixtures / "m4-tick17.sqlite3", database)
    connection = sqlite3.connect(database)
    identifier = connection.execute("SELECT id FROM experiments").fetchone()[0]
    before = history_digest(connection, identifier)

    def fail(stage):
        if stage == 1:
            raise OSError("injected M4 migration failure")

    monkeypatch.setattr(storage, "migration_hook", fail)
    with pytest.raises(OSError):
        storage.migrate(connection, database)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
    assert history_digest(connection, identifier) == before
    assert not connection.execute(
        "SELECT name FROM sqlite_master WHERE name='neural_snapshots'"
    ).fetchall()
    backup = next(tmp_path.glob("lab.pre-m4-*.sqlite3"))
    with closing(sqlite3.connect(backup)) as archived:
        assert archived.execute("PRAGMA user_version").fetchone()[0] == 2
        assert history_digest(archived, identifier) == before
    monkeypatch.setattr(storage, "migration_hook", lambda stage: None)
    storage.migrate(connection, database)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
    assert history_digest(connection, identifier) == before
    connection.close()
