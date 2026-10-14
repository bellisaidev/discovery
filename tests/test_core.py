import sys
from dataclasses import replace

import numpy as np
import pytest

from digital_ecosystem.brain import Action
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation


def quiet_config():
    config = Configuration()
    config.neural.plasticity = False
    config.signals.enabled = False
    config.world.resource_count = 0
    config.reproduction.threshold = 1.0
    config.body.movement_cost = 0
    config.body.rotation_cost = 0
    config.body.harvesting_cost = 0
    return config


def test_initial_population_and_neural_actions():
    simulation = Simulation(seed=42)
    assert len(simulation.world.organisms) == 10
    assert {len(o.genome.nodes) for o in simulation.world.organisms.values()} == {30}
    assert {len(o.genome.connections) for o in simulation.world.organisms.values()} == {176}
    before = [o.position.copy() for o in simulation.world.organisms.values()]
    simulation.step()
    assert any(
        not np.array_equal(p, o.position)
        for p, o in zip(before, simulation.world.organisms.values(), strict=True)
    )
    for o in simulation.world.organisms.values():
        assert np.all((o.sensors >= 0) & (o.sensors <= 1))
        np.testing.assert_array_equal(o.outputs, o.brain.last_outputs)
    assert "pygame" not in sys.modules


def test_metabolism_and_energy_ledger():
    config = quiet_config()
    simulation = Simulation(config)
    organism = simulation.world.organisms[1]
    before = organism.energy
    simulation.step()
    assert organism.energy == pytest.approx(before - config.body.metabolism * config.world.dt)
    assert simulation.world.ledger.metabolic_dissipation == pytest.approx(
        10 * config.body.metabolism * config.world.dt
    )
    assert simulation.world.energy_balance_error() == pytest.approx(0, abs=1e-9)


def test_resource_transfer_and_concurrent_sharing():
    config = quiet_config()
    config.world.initial_population = 2
    config.world.resource_count = 1
    simulation = Simulation(config)
    world = simulation.world
    world.resource_positions[0] = [500, 350]
    world.resource_index.rebuild([(0, world.resource_positions[0])])
    a, b = world.organisms.values()
    a.position[:] = [494, 350]
    b.position[:] = [506, 350]
    world.resource_energy[0] = 0.2
    world.ledger.initial = world.total_energy()
    before = a.energy
    simulation.physics.harvest({a.id: 1, b.id: 1})
    assert a.energy == pytest.approx(before + 0.1)
    assert a.energy == b.energy
    assert world.resource_energy[0] == pytest.approx(0)
    assert world.ledger.harvested == pytest.approx(0.2)
    assert world.energy_balance_error() == pytest.approx(0, abs=1e-9)
    simulation.physics.harvest({a.id: 1, b.id: 1})
    assert world.ledger.harvested == pytest.approx(0.2)


def test_regeneration_is_external_energy():
    config = quiet_config()
    config.world.resource_count = 1
    simulation = Simulation(config)
    simulation.world.resource_energy[:] = 0
    simulation.world.ledger.initial = simulation.world.total_energy()
    simulation.world.regenerate()
    assert simulation.world.ledger.regenerated == pytest.approx(
        config.world.resource_regeneration * config.world.dt
    )
    assert simulation.world.energy_balance_error() == pytest.approx(0, abs=1e-9)


def test_death_extinction_and_no_respawn():
    config = quiet_config()
    config.body.initial_energy = 0.001
    simulation = Simulation(config)
    simulation.step()
    assert not simulation.world.organisms
    assert simulation.deaths == 10
    for _ in range(100):
        simulation.step()
    assert not simulation.world.organisms
    assert simulation.tick == 101
    assert all(r["death_cause"] == "energy_exhaustion" for r in simulation.records.values())
    assert simulation.world.energy_balance_error() == pytest.approx(0, abs=1e-10)


def test_age_death_dissipates_remaining_energy():
    config = quiet_config()
    config.body.max_age = config.world.dt
    simulation = Simulation(config)
    simulation.step()
    assert not simulation.world.organisms
    assert simulation.world.ledger.death_dissipation > 0
    assert simulation.world.energy_balance_error() == pytest.approx(0, abs=1e-9)


def test_collision_coincident_centers_and_walls():
    simulation = Simulation(quiet_config())
    a, b = simulation.world.organisms[1], simulation.world.organisms[2]
    a.position[:] = [500, 350]
    b.position[:] = a.position
    simulation.physics.resolve_collisions()
    assert np.linalg.norm(a.position - b.position) >= a.radius + b.radius - 1e-7
    assert simulation.physics.contacts >= 1
    a.position[:] = [-100, 900]
    a.velocity[:] = [-2, 3]
    simulation.physics._walls(a)
    np.testing.assert_array_equal(a.position, [6, 694])
    np.testing.assert_array_equal(a.velocity, [0, 0])


def test_action_cost_cannot_make_negative_energy():
    simulation = Simulation(quiet_config())
    simulation.config.body.movement_cost = 100
    organism = simulation.world.organisms[1]
    organism.energy = 1e-6
    actions = {i: Action(1, 1, 0, 0, 0, 0) for i in simulation.world.organisms}
    simulation.physics.advance(actions)
    assert all(o.energy >= 0 for o in simulation.world.organisms.values())


def test_snapshot_cannot_mutate_world():
    simulation = Simulation(quiet_config())
    snapshot = simulation.snapshot()
    snapshot["organisms"][0]["position"][:] = -100
    snapshot["resource_energy"][:] = -10
    assert np.all(simulation.world.organisms[1].position > 0)


def test_oriented_local_sensors_do_not_see_remote_resources():
    config = quiet_config()
    config.world.initial_population = 1
    config.world.resource_count = 2
    simulation = Simulation(config)
    organism = simulation.world.organisms[1]
    organism.position[:] = [500, 350]
    organism.orientation = 0
    simulation.world.resource_positions[:] = [[530, 350], [900, 650]]
    simulation.world.resource_index.rebuild(list(enumerate(simulation.world.resource_positions)))
    values = simulation.sensors.read(organism)
    assert values[1] > 0 and values[2] == values[3] == 0
    organism.orientation = np.pi / 2
    rotated = simulation.sensors.read(organism)
    assert rotated[3] > 0 and rotated[1] == rotated[2] == 0
    simulation.world.resource_energy[0] = 0
    assert np.all(simulation.sensors.read(organism)[1:4] == 0)


def test_collision_at_wall_resolves_full_overlap():
    config = quiet_config()
    config.world.initial_population = 2
    simulation = Simulation(config)
    a, b = simulation.world.organisms.values()
    a.position[:] = [6, 6]
    b.position[:] = [6, 6]
    simulation.physics.resolve_collisions()
    assert np.linalg.norm(a.position - b.position) >= a.radius + b.radius - 1e-7
    assert np.all(a.position >= a.radius)
    assert np.all(b.position >= b.radius)


@pytest.mark.parametrize("seed", [0, 42, 123])
def test_determinism(seed):
    a, b = Simulation(seed=seed), Simulation(seed=seed)
    for _ in range(50):
        a.step()
        # Inspecting state must not alter dynamics or randomness.
        b.snapshot()
        b.step()
    assert a.state_fingerprint() == b.state_fingerprint()


def test_configuration_validation(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[world]\ndt = nan\n", encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        Configuration.load(path)
    config = Configuration()
    config.world = replace(config.world, initial_population=300)
    with pytest.raises(ValueError, match="capacity"):
        config.validate()


def test_default_cli_configuration_is_experimental_preset():
    assert (
        Configuration.load().to_dict() == Configuration.load("configs/experimental.toml").to_dict()
    )
