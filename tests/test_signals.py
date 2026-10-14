import numpy as np
import pytest

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.signals import SignalField
from digital_ecosystem.simulation import Simulation


@pytest.mark.parametrize("diffusion", [0, 150, 1e6])
def test_aggregate_matches_per_emitter_reference_and_self_exclusion(diffusion):
    config = Configuration()
    config.signals.columns = 8
    config.signals.rows = 6
    config.signals.lifetime_ticks = 7
    config.signals.diffusion = diffusion
    field = SignalField(config)
    histories = {1: [], 2: []}
    rng = np.random.default_rng(62)
    for tick in range(1, 30):
        emissions = []
        for identifier in (1, 2):
            # Emitter 1 dies; its trace must persist and then expire.
            if identifier == 1 and tick > 12:
                continue
            position = rng.uniform([0, 0], [1000, 700])
            amplitude = rng.random(2)
            emissions.append((identifier, position, amplitude))
        reference = {}
        for identifier in histories:
            history = histories[identifier]
            history[:] = [
                (born, field.propagate(grid))
                for born, grid in history
                if tick - born < config.signals.lifetime_ticks
            ]
            for emitted_id, position, amplitude in emissions:
                if identifier == emitted_id:
                    x, y = field.cell(position)
                    grid = np.zeros_like(field.field)
                    grid[:, y, x] = amplitude
                    history.append((tick, grid))
            reference[identifier] = sum((grid for _, grid in history), np.zeros_like(field.field))
        field.advance(emissions)
        np.testing.assert_allclose(field.field, reference[1] + reference[2], atol=2e-12)
        points = np.array([[0, 0], [1000, 700], [430, 260], [625, 349]])
        for identifier in (1, 2):
            # A separate reference field holds only emissions from the other body.
            other = SignalField(config)
            other.field[:] = reference[3 - identifier]
            np.testing.assert_allclose(
                field.sample(points, exclude=identifier), other.sample(points), atol=2e-12
            )
        assert np.all(field.field >= 0)
        assert len(field.history) <= config.signals.lifetime_ticks
    assert 1 not in field.own_history


def test_decay_channel_independence_and_expiration():
    config = Configuration()
    config.signals.lifetime_ticks = 4
    field = SignalField(config)
    position = np.array([500, 350])
    field.advance([(1, position, np.array([1.0, 0.0]))])
    assert np.all(field.field[1] == 0)
    assert field.field.sum() == pytest.approx(1)
    assert field.sample(np.array([position]), exclude=1).max() < 1e-12
    field.advance([])
    assert field.field.sum() == pytest.approx(field.decay)
    for _ in range(3):
        field.advance([])
    assert field.field.max() < 1e-12


def test_disabled_signals_are_absent_from_sensors_and_costs():
    config = Configuration()
    config.signals.enabled = False
    simulation = Simulation(config)
    assert simulation.signals is None
    simulation.step()
    assert all(np.all(o.sensors[10:] == 0) for o in simulation.world.organisms.values())


def test_kernel_bounds_and_memory_do_not_scale_with_full_per_body_fields():
    config = Configuration()
    field = SignalField(config)
    for transition in (field.px, field.py):
        np.testing.assert_allclose(transition.sum(axis=0), 1, atol=1e-12)
        assert np.all(transition >= 0)
    for _ in range(config.signals.lifetime_ticks):
        field.advance([(i, np.array([500, 350]), np.ones(2)) for i in range(256)])
    per_body_bytes = 256 * 2 * config.signals.rows * config.signals.columns * 8
    assert field.memory_bytes() < per_body_bytes
