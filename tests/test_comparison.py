import sqlite3
from itertools import product
from pathlib import Path

import numpy as np
import pytest

from digital_ecosystem.comparison import run_comparison
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_all_controls_multi_seed_are_deterministic(seed):
    for plasticity, mutations, signaling in product((False, True), repeat=3):
        config = Configuration.load(Path("configs/diagnostic.toml"))
        config.neural.plasticity = plasticity
        config.neural.mutations = mutations
        config.signals.enabled = signaling
        a, b = Simulation(config, seed), Simulation(config, seed)
        signatures = {o.id: o.genome.signature() for o in a.world.organisms.values()}
        for _ in range(5):
            a.step()
            b.step()
        assert a.state_fingerprint() == b.state_fingerprint()
        assert a.world.energy_balance_error() == pytest.approx(0, abs=1e-8)
        if not plasticity:
            assert all(np.all(o.brain.acquired == 0) for o in a.world.organisms.values())
        if not mutations:
            for organism in a.world.organisms.values():
                ancestor = organism
                while ancestor.parent_id:
                    ancestor = a.world.organisms[ancestor.parent_id]
                assert organism.genome.signature() == signatures[ancestor.id]
        if not signaling:
            assert a.signals is None


def test_factorial_runner_keeps_individual_runs_and_dispersion(tmp_path):
    report = run_comparison(Configuration.load("configs/diagnostic.toml"), [0, 1, 2], 2, tmp_path)
    assert len(report["conditions"]) == 8
    assert all(metrics["population"]["n"] == 3 for metrics in report["conditions"].values())
    assert (tmp_path / "comparison_runs.csv").exists()
    assert (tmp_path / "comparison.json").exists()
    with sqlite3.connect(tmp_path / "lab.sqlite3") as connection:
        assert connection.execute("SELECT count(*) FROM experiments").fetchone()[0] == 24
    with pytest.raises(ValueError, match="distinct"):
        run_comparison(Configuration(), [42], 1, tmp_path)
