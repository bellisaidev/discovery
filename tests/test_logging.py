import csv
import json
import sqlite3
from pathlib import Path

import pytest

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.simulation import Simulation


def test_sqlite_csv_initial_final_events_and_metadata(tmp_path):
    config = Configuration.load(Path("configs/diagnostic.toml"))
    config.logging.sample_interval = 3
    simulation = Simulation(config)
    logger = ExperimentLogger(simulation, tmp_path)
    for _ in range(5):
        simulation.step()
        logger.observe()
    summary = logger.close()
    assert summary["births"] > 0
    with sqlite3.connect(logger.database) as connection:
        ticks = connection.execute("SELECT tick FROM samples ORDER BY tick").fetchall()
        assert ticks == [(0,), (3,), (5,)]
        experiment = connection.execute(
            "SELECT status, config_json, software_json, ended_at FROM experiments"
        ).fetchone()
        assert experiment[0] == "completed" and experiment[3]
        assert json.loads(experiment[1]) == config.to_dict()
        assert "python" in json.loads(experiment[2])
        assert connection.execute("SELECT count(*) FROM events WHERE kind='birth'").fetchone()[0]
        assert connection.execute("SELECT sum(offspring) FROM individuals").fetchone()[0] == (
            simulation.births
        )
        assert connection.execute("SELECT count(*) FROM resources").fetchone()[0] == (
            config.world.resource_count * 3
        )
    destination = logger.export_csv()
    for table in ("experiments", "samples", "resources", "events", "individuals"):
        with (destination / f"{table}.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream))
        assert len(rows) >= 2
    with pytest.raises(RuntimeError, match="closed"):
        logger.observe()


def test_logger_does_not_change_dynamics(tmp_path):
    config = Configuration.load(Path("configs/diagnostic.toml"))
    config.logging.sample_interval = 1
    a, b = Simulation(config, seed=3), Simulation(config, seed=3)
    logger = ExperimentLogger(b, tmp_path)
    for _ in range(30):
        a.step()
        b.step()
        logger.observe()
    logger.close()
    assert a.state_fingerprint() == b.state_fingerprint()


def test_interruption_deaths_censored_lifetimes_and_energy(tmp_path):
    config = Configuration()
    config.body.max_age = config.world.dt
    simulation = Simulation(config)
    logger = ExperimentLogger(simulation, tmp_path)
    simulation.step()
    logger.observe()
    logger.close("interrupted")
    with sqlite3.connect(logger.database) as connection:
        assert connection.execute("SELECT status FROM experiments").fetchone()[0] == "interrupted"
        lifetimes = connection.execute("SELECT lifespan, death_cause FROM individuals").fetchall()
        assert all(age == config.world.dt and cause == "age_limit" for age, cause in lifetimes)
        error = connection.execute("SELECT balance_error FROM samples WHERE tick=1").fetchone()[0]
        assert abs(error) < 1e-8


def test_living_lifespan_is_censored(tmp_path):
    simulation = Simulation()
    logger = ExperimentLogger(simulation, tmp_path)
    simulation.step()
    logger.close()
    with sqlite3.connect(logger.database) as connection:
        lifetimes = connection.execute("SELECT lifespan, observed_age FROM individuals").fetchall()
        assert all(lifespan is None and age > 0 for lifespan, age in lifetimes)
