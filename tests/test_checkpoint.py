import copy
import json
import shutil
import sqlite3
import subprocess
import sys
import zipfile
import zlib
from contextlib import closing
from itertools import product

import pytest

from digital_ecosystem import checkpoint, storage
from digital_ecosystem.checkpoint import CheckpointManager, read_checkpoint, resume
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.genome import Genome
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.state import canonical_json, fingerprint


def session(directory, seed=42, diagnostic=True):
    config = Configuration.load("configs/diagnostic.toml" if diagnostic else None)
    simulation = Simulation(config, seed)
    logger = ExperimentLogger(simulation, directory)
    return simulation, logger, CheckpointManager(logger)


def advance(simulation, logger, ticks):
    for _ in range(ticks):
        simulation.step()
        logger.observe()


def rows(database, table, identifier):
    with closing(sqlite3.connect(database)) as connection:
        columns = [
            r[1]
            for r in connection.execute(f"PRAGMA table_info({table})")
            if r[1] not in {"experiment_id", "event_id"}
        ]
        return sorted(
            connection.execute(
                f"SELECT {','.join(columns)} FROM {table} WHERE experiment_id=?", (identifier,)
            ).fetchall(),
            key=repr,
        )


def test_sqlite_full_retries_entire_uncommitted_observation_batch(tmp_path):
    config = Configuration.load("configs/diagnostic.toml")
    config.logging.sample_interval = 1
    config.logging.batch_samples = 100
    simulation = Simulation(config, 42)
    logger = ExperimentLogger(simulation, tmp_path / "recover")
    control = Simulation(copy.deepcopy(config), 42)
    reference = ExperimentLogger(control, tmp_path / "control")
    for engine, observer in ((simulation, logger), (control, reference)):
        advance(engine, observer, 3)
        engine._event(
            {"tick": engine.tick, "kind": "test", "organism_id": 1, "payload": "x" * 1000000}
        )
    page_count = logger.connection.execute("PRAGMA page_count").fetchone()[0]
    logger.connection.execute(f"PRAGMA max_page_count={page_count}")
    with pytest.raises(RuntimeError, match="full"):
        logger.flush()
    assert not logger.connection.in_transaction
    logger.connection.execute("PRAGMA max_page_count=1000000000")
    logger.flush()
    reference.flush()
    assert simulation.state_fingerprint() == control.state_fingerprint()
    for table in ("events", "samples", "resources", "individuals", "birth_genomes"):
        assert rows(logger.database, table, logger.experiment_id) == rows(
            reference.database, table, reference.experiment_id
        )
    logger.close()
    reference.close()


def test_partial_observation_write_can_retry_after_sqlite_rollback(tmp_path):
    simulation, logger, manager = session(tmp_path)
    logger.connection.execute(
        "CREATE TEMP TRIGGER fail_observation BEFORE INSERT ON individuals "
        "BEGIN SELECT RAISE(FAIL, 'simulated write failure'); END"
    )
    logger.connection.commit()
    simulation.step()
    with pytest.raises(RuntimeError, match="simulated write failure"):
        manager.save()
    logger.connection.execute("DROP TRIGGER fail_observation")
    logger.connection.commit()
    path = manager.save()
    with read_checkpoint(path) as (restored, _, _):
        assert restored.state_fingerprint() == simulation.state_fingerprint()
    assert logger.connection.execute(
        "SELECT count(*) FROM resources WHERE experiment_id=? AND tick=1",
        (logger.experiment_id,),
    ).fetchone()[0] == len(simulation.world.resource_energy)
    logger.close()


def test_sqlite_export_failure_preserves_checkpoint_and_allows_retry(tmp_path, monkeypatch):
    simulation, logger, manager = session(tmp_path)
    previous = manager.save()
    simulation.step()
    exporter = checkpoint.export_experiment

    def fail(*args):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(checkpoint, "export_experiment", fail)
    with pytest.raises(RuntimeError, match="export failed"):
        manager.save()
    assert list(manager.directory.glob("*.dlcp")) == [previous]
    monkeypatch.setattr(checkpoint, "export_experiment", exporter)
    path = manager.save()
    with read_checkpoint(path) as (restored, _, _):
        assert restored.tick == 1
    logger.close()


@pytest.mark.parametrize("seed", [0, 1, 2])
@pytest.mark.parametrize("plasticity,mutations,signaling", list(product((False, True), repeat=3)))
def test_multiple_resumes_equal_continuous_complete_state_and_events(
    tmp_path, seed, plasticity, mutations, signaling
):
    config = Configuration.load("configs/diagnostic.toml")
    config.neural.plasticity = plasticity
    config.neural.mutations = mutations
    config.signals.enabled = signaling
    a, b = Simulation(config, seed), Simulation(config, seed)
    la, lb = ExperimentLogger(a, tmp_path / "continuous"), ExperimentLogger(b, tmp_path / "split")
    for stop in (17, 41, 120):
        while a.tick < stop:
            a.step()
            la.observe()
            b.step()
            lb.observe()
        path = CheckpointManager(lb).save()
        la.flush()
        assert fingerprint(a.to_state()) == fingerprint(b.to_state())
        lb.close()
        previous_id = lb.experiment_id
        b, lb = resume(path, tmp_path / "split")
        assert lb.experiment_id == previous_id
        assert fingerprint(a.to_state()) == fingerprint(b.to_state())
    la.close()
    lb.close()
    assert rows(la.database, "events", la.experiment_id) == rows(
        lb.database, "events", lb.experiment_id
    )
    assert rows(la.database, "individuals", la.experiment_id) == rows(
        lb.database, "individuals", lb.experiment_id
    )
    assert rows(la.database, "samples", la.experiment_id) == rows(
        lb.database, "samples", lb.experiment_id
    )


def test_full_state_preserves_structural_order_rng_and_cooldown():
    config = Configuration.load("configs/diagnostic.toml")
    config.neural.add_node_probability = 1
    simulation = Simulation(config, seed=42)
    simulation.step()
    assert simulation.births
    assert any(len(o.genome.nodes) > 30 for o in simulation.world.organisms.values())
    before = simulation.to_state()
    restored = Simulation.from_state(before)
    assert fingerprint(before) == fingerprint(restored.to_state())
    assert any(o.last_birth_age > -1e20 for o in restored.world.organisms.values())
    for _ in range(130):
        simulation.step()
        restored.step()
    assert fingerprint(simulation.to_state()) == fingerprint(restored.to_state())


def test_self_contained_scoped_restore_without_original_database(tmp_path):
    simulation, logger, manager = session(tmp_path / "original")
    advance(simulation, logger, 20)
    path = manager.save()
    other, other_logger, _ = session(tmp_path / "original", seed=123)
    advance(other, other_logger, 2)
    other_logger.close()
    archive = tmp_path / "moved" / "portable.dlcp"
    archive.parent.mkdir()
    shutil.copyfile(path, archive)
    original_id = logger.experiment_id
    logger.close()
    inaccessible = tmp_path / "unavailable"
    (tmp_path / "original").rename(inaccessible)
    with read_checkpoint(archive) as (_, manifest, snapshot):
        with closing(sqlite3.connect(snapshot)) as connection:
            assert connection.execute("SELECT id FROM experiments").fetchall() == [(original_id,)]
            assert connection.execute("SELECT count(*) FROM genomes").fetchone()[0] > 0
            genomes = connection.execute("SELECT content_id,payload FROM genomes").fetchall()
            for key, payload in genomes:
                import hashlib

                assert hashlib.sha256(zlib.decompress(payload)).hexdigest() == key
                Genome.from_data(json.loads(zlib.decompress(payload)), simulation.config.neural)
    restored, new_logger = resume(archive)  # Default output is the archive's directory.
    assert new_logger.output == archive.resolve().parent
    assert restored.state_fingerprint() == simulation.state_fingerprint()
    advance(restored, new_logger, 10)
    new_logger.close()
    assert rows(
        inaccessible / "lab.sqlite3",
        "events",
        original_id,
    ) == [r for r in rows(new_logger.database, "events", original_id) if r[0] <= 20]


def test_old_checkpoint_forks_and_preserves_original_future(tmp_path):
    simulation, logger, manager = session(tmp_path)
    advance(simulation, logger, 5)
    path = manager.save()
    saved = simulation.to_state()
    advance(simulation, logger, 100)
    logger.close()
    original = {
        table: rows(logger.database, table, logger.experiment_id)
        for table in ("samples", "events", "individuals", "resources", "birth_genomes")
    }
    restored, fork = resume(path, tmp_path)
    assert fork.experiment_id != logger.experiment_id
    assert fingerprint(restored.to_state()) == fingerprint(saved)
    advance(restored, fork, 10)
    fork.close()
    for table, expected in original.items():
        assert rows(logger.database, table, logger.experiment_id) == expected
    with closing(sqlite3.connect(fork.database)) as connection:
        assert connection.execute(
            "SELECT parent_experiment_id,fork_tick FROM experiment_origins WHERE experiment_id=?",
            (fork.experiment_id,),
        ).fetchone() == (logger.experiment_id, 5)


def test_same_tick_divergent_history_forks(tmp_path):
    _, logger, manager = session(tmp_path)
    path = manager.save()
    logger.close()
    with sqlite3.connect(logger.database) as connection:
        connection.execute(
            "UPDATE samples SET mean_energy=mean_energy+1 WHERE experiment_id=?",
            (logger.experiment_id,),
        )
    _, fork = resume(path, tmp_path)
    assert fork.experiment_id != logger.experiment_id
    fork.close()


def test_events_are_idempotent_and_conflicts_are_rejected(tmp_path):
    simulation, logger, _ = session(tmp_path)
    simulation.step()
    events = copy.deepcopy(simulation.events)
    assert events
    logger.observe()
    logger.append_events(events)
    logger.flush()
    assert len(rows(logger.database, "events", logger.experiment_id)) == len(events)
    bad = dict(events[0], kind="changed")
    with pytest.raises(ValueError, match="Conflicting"):
        logger.append_events([bad])
    logger.close()


def test_rotation_coalescing_and_failed_publication(tmp_path, monkeypatch):
    simulation, logger, manager = session(tmp_path)
    first = manager.save()
    assert manager.save("close") == first
    assert len(list(manager.directory.glob("*.dlcp"))) == 1
    for _ in range(5):
        advance(simulation, logger, 1)
        manager.save()
    retained = set(manager.directory.glob("*.dlcp"))
    assert len(retained) == 4
    advance(simulation, logger, 1)

    def fail(stage):
        if stage == "before_publish":
            raise OSError("simulated disk failure")

    monkeypatch.setattr(checkpoint, "fault_hook", fail)
    with pytest.raises(OSError, match="disk"):
        manager.save()
    assert set(manager.directory.glob("*.dlcp")) == retained
    for path in retained:
        with read_checkpoint(path):
            pass
    logger.close()


@pytest.mark.parametrize("member", ["state.json", "experiment.sqlite3", "arrays/00000.npy"])
def test_corrupt_checksums_are_rejected_before_destination_changes(tmp_path, member):
    _, logger, manager = session(tmp_path / "source")
    path = manager.save()
    logger.close()
    bad = tmp_path / "corrupt.dlcp"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(bad, "w") as target:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename == member:
                payload = payload[:-1] + bytes([payload[-1] ^ 1])
            target.writestr(entry.filename, payload)
    destination = tmp_path / "destination"
    with pytest.raises((ValueError, UnicodeDecodeError)):
        resume(bad, destination)
    assert not destination.exists()


def test_truncated_and_incompatible_archives(tmp_path):
    _, logger, manager = session(tmp_path)
    path = manager.save()
    logger.close()
    bad = tmp_path / "truncated.dlcp"
    bad.write_bytes(path.read_bytes()[:100])
    with pytest.raises(ValueError, match="Invalid checkpoint"):
        resume(bad)
    incompatible = tmp_path / "incompatible.dlcp"
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(incompatible, "w") as target:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename == "manifest.json":
                manifest = json.loads(payload)
                manifest["compatibility"]["python"] = "different"
                payload = canonical_json(manifest)
            target.writestr(entry.filename, payload)
    with pytest.raises(ValueError, match="incompatible"):
        resume(incompatible)


def test_dead_emitter_traces_and_extinction_restore(tmp_path):
    config = Configuration()
    config.body.max_age = config.world.dt * 2
    simulation = Simulation(config)
    logger = ExperimentLogger(simulation, tmp_path)
    advance(simulation, logger, 2)
    assert not simulation.world.organisms
    assert simulation.signals.field.sum() > 0
    path = CheckpointManager(logger).save()
    logger.close()
    restored, resumed_logger = resume(path, tmp_path / "copy")
    for _ in range(40):
        simulation.step()
        restored.step()
        resumed_logger.observe()
    assert simulation.state_fingerprint() == restored.state_fingerprint()
    assert not restored.signals.own_history
    resumed_logger.close()


def test_partial_tick_cannot_be_saved(tmp_path, monkeypatch):
    simulation, logger, manager = session(tmp_path)
    path = manager.save()

    def broken(actions):
        raise RuntimeError("mid-tick failure")

    monkeypatch.setattr(simulation.physics, "advance", broken)
    with pytest.raises(RuntimeError):
        simulation.step()
    with pytest.raises(ValueError, match="partial"):
        manager.save()
    logger.close("failed")
    assert path.exists()


def test_writer_lock_prevents_simultaneous_resume(tmp_path):
    _, logger, manager = session(tmp_path)
    path = manager.save()
    with pytest.raises(RuntimeError, match="another writer"):
        resume(path, tmp_path)
    logger.close()
    _, resumed = resume(path, tmp_path)
    resumed.close()


def test_writer_lock_is_checked_before_database_access(tmp_path):
    simulation, logger, manager = session(tmp_path)
    path = manager.save()
    simulation.step()
    logger.observe()  # Births leave a pending SQLite write transaction.
    assert logger.connection.in_transaction
    with pytest.raises(RuntimeError, match="another writer"):
        resume(path, tmp_path)
    logger.close()


def test_compressed_resource_geometry_preserves_all_historical_positions(tmp_path):
    config = Configuration()
    config.logging.sample_interval = 1
    config.world.resource_count = 2
    simulation = Simulation(config)
    logger = ExperimentLogger(simulation, tmp_path)
    advance(simulation, logger, 1)
    simulation.world.resource_positions[0] = [300, 200]
    simulation.world.resource_index.rebuild(list(enumerate(simulation.world.resource_positions)))
    advance(simulation, logger, 1)
    simulation.world.resource_positions[0] = [400, 250]
    simulation.world.resource_index.rebuild(list(enumerate(simulation.world.resource_positions)))
    advance(simulation, logger, 1)
    path = CheckpointManager(logger).save()
    logger.close()
    restored, copy_logger = resume(path, tmp_path / "copy")
    assert restored.state_fingerprint() == simulation.state_fingerprint()
    assert rows(logger.database, "resources", logger.experiment_id) == rows(
        copy_logger.database, "resources", copy_logger.experiment_id
    )
    with read_checkpoint(path) as (_, _, snapshot):
        with closing(sqlite3.connect(snapshot)) as connection:
            assert (
                connection.execute("SELECT count(*) FROM resource_geometry_history").fetchone()[0]
                == 4
            )
    copy_logger.close()


@pytest.mark.parametrize(
    "stage",
    [
        "after_flush",
        "after_export",
        "after_arrays",
        "after_archive",
        "before_publish",
        "after_publish",
        "before_rotation",
    ],
)
def test_abrupt_process_death_at_publication_boundaries(tmp_path, stage):
    root = tmp_path / "session"
    script = """
import os,sys
from pathlib import Path
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem import checkpoint
s=Simulation(Configuration.load('configs/diagnostic.toml'))
l=ExperimentLogger(s,Path(sys.argv[1]))
m=checkpoint.CheckpointManager(l)
m.save()
s.step(); l.observe()
checkpoint.fault_hook=lambda stage: os._exit(77) if stage==sys.argv[2] else None
m.save()
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root), stage], capture_output=True, text=True
    )
    assert result.returncode == 77, result.stderr
    paths = sorted(root.glob("checkpoints/**/*.dlcp"))
    assert paths
    for path in paths:
        with read_checkpoint(path):
            pass
    # The OS released the writer lock; the older version can fork from committed progress.
    _, recovered = resume(paths[0], root)
    recovered.close()


def test_migration_failure_rolls_back_and_preserves_backup(tmp_path, monkeypatch):
    simulation, logger, _ = session(tmp_path)
    logger.close()
    # Build a genuine V1 legacy schema from the pre-migration API.
    legacy = tmp_path / "legacy.sqlite3"
    fake = ExperimentLogger.__new__(ExperimentLogger)
    fake.connection = sqlite3.connect(legacy)
    fake._schema()
    fake.connection.execute(
        "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?)",
        ("legacy", 1, "0.1.0", "start", None, "completed", "{}", "{}", None),
    )
    fake.connection.commit()

    def fail(stage):
        if stage == 2:
            raise OSError("migration interrupted")

    monkeypatch.setattr(storage, "migration_hook", fail)
    with pytest.raises(OSError):
        storage.migrate(fake.connection, legacy)
    assert fake.connection.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "event_seq" not in [r[1] for r in fake.connection.execute("PRAGMA table_info(events)")]
    assert list(tmp_path.glob("legacy.pre-m4-*.sqlite3"))
    monkeypatch.setattr(storage, "migration_hook", lambda stage: None)
    storage.migrate(fake.connection, legacy)
    assert fake.connection.execute("PRAGMA user_version").fetchone()[0] == storage.SCHEMA_VERSION
    assert fake.connection.execute("SELECT count(*) FROM genomes").fetchone()[0] == 0
    fake.connection.close()


def test_resume_cli_keeps_seed_config_and_counts_additional_steps(tmp_path):
    config = Configuration.load("configs/diagnostic.toml")
    config.neural.plasticity = False
    simulation = Simulation(config, seed=77)
    logger = ExperimentLogger(simulation, tmp_path / "source")
    manager = CheckpointManager(logger)
    advance(simulation, logger, 4)
    path = manager.save()
    logger.close()
    destination = tmp_path / "new"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "digital_ecosystem",
            "--headless",
            "--resume",
            str(path),
            "--steps",
            "3",
            "--output",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert data["tick"] == 7
    with closing(sqlite3.connect(destination / "lab.sqlite3")) as connection:
        seed, parameters = connection.execute("SELECT seed,config_json FROM experiments").fetchone()
        assert seed == 77
        # Config is captured in the checkpoint, not silently replaced by CLI defaults.
        assert json.loads(parameters)["body"]["initial_energy"] == 180
        assert json.loads(parameters)["neural"]["plasticity"] is False
    for explicit in (
        ["--seed", "42"],
        ["--config", "configs/experimental.toml"],
        ["--no-plasticity"],
        ["--no-mutations"],
        ["--no-signaling"],
        ["--compare-seeds", "0,1,2"],
    ):
        rejected = subprocess.run(
            [
                sys.executable,
                "-m",
                "digital_ecosystem",
                "--resume",
                str(path),
                "--headless",
                "--steps",
                "0",
                *explicit,
            ],
            capture_output=True,
            text=True,
        )
        assert rejected.returncode == 2
