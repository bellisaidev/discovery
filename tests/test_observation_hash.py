import math

import numpy as np
import pytest

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.observation_hash import engine_fingerprint, fingerprint_fast
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.state import fingerprint


def test_optimized_observer_hash_is_byte_equivalent_to_m4_serialization():
    values = [
        None,
        True,
        False,
        0,
        -1,
        2**90,
        0.0,
        -0.0,
        1e-200,
        1e200,
        np.float64(1.2345678901234567),
        'caffè\n"\t🌍',
        (),
        [],
        {},
        np.arange(15, dtype=">i4").reshape(3, 5)[:, ::2],
        np.array([(1, 2.5)], dtype=[("id", "i4"), ("value", "f8")]),
        [{(True,): 1}, {(1,): 2}, {-0.0: "minus"}, {0.0: "plus"}],
        {"nested": (False, {"a": [1, 2, 3.14]})},
        # Exercise the bounded local caches beyond their capacity.
        [{f"key{i}": [f"value{i}", i, i + 0.1]} for i in range(5000)],
    ]
    assert fingerprint_fast(values) == fingerprint(values)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_optimized_observer_hash_rejects_nonfinite_scalars_like_m4(value):
    for calculate in (fingerprint, fingerprint_fast):
        with pytest.raises(ValueError):
            calculate({"value": value})


@pytest.mark.parametrize("seed", [1, 42, 54321])
def test_optimized_observer_provenance_matches_real_m4_engine_hash(seed):
    simulation = Simulation(Configuration.load("configs/diagnostic.toml"), seed)
    for tick in range(31):
        if tick in (0, 1, 17, 30):
            before = fingerprint(simulation.to_state())
            assert engine_fingerprint(simulation) == simulation.state_fingerprint()
            assert fingerprint(simulation.to_state()) == before
        simulation.step()
