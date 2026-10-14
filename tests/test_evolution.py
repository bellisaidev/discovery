from pathlib import Path

import numpy as np
import pytest

from digital_ecosystem.brain import Brain
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.genome import Connection, Genome
from digital_ecosystem.simulation import Simulation


def reproductive_simulation():
    config = Configuration()
    config.world.initial_population = 1
    config.world.resource_count = 0
    config.signals.enabled = False
    config.body.initial_energy = 200
    config.neural.mutations = False
    config.neural.plasticity = False
    simulation = Simulation(config)
    parent = simulation.world.organisms[1]
    parent.position[:] = [500, 350]
    parent.genome.connections.clear()
    for node in parent.genome.nodes.values():
        node.bias = 0
    parent.genome.nodes[21].bias = 2.0
    parent.brain = Brain(parent.genome, config.neural)
    return simulation, parent


def test_birth_is_neural_and_energy_conserving():
    simulation, parent = reproductive_simulation()
    initial = simulation.world.total_energy()
    simulation.step()
    assert parent.outputs[5] > simulation.config.reproduction.threshold
    assert simulation.births == 1
    child = simulation.world.organisms[2]
    assert child.parent_id == parent.id
    assert child.lineage_id == parent.lineage_id
    assert child.generation == 1
    assert child.energy == simulation.config.reproduction.offspring_energy
    assert simulation.world.ledger.inherited == child.energy
    assert simulation.world.ledger.reproductive_dissipation == simulation.config.reproduction.cost
    assert simulation.world.total_energy() == pytest.approx(
        initial - simulation.world.ledger.dissipated
    )
    assert simulation.records[1]["descendants"] == 1
    assert child.genome.signature() == parent.genome.signature()
    child.genome.nodes[21].bias = -1
    assert parent.genome.nodes[21].bias == 2
    simulation.step()
    assert parent.offspring == 1  # physical cooldown


def test_birth_requires_control_and_energy():
    simulation, parent = reproductive_simulation()
    parent.outputs[5] = 0
    assert simulation.reproduction.attempt(parent, 0) == (None, None)
    parent.outputs[5] = 1
    parent.energy = 1
    assert simulation.reproduction.attempt(parent, 0) == (None, None)


def test_capacity_and_placement_do_not_charge_parent():
    simulation, parent = reproductive_simulation()
    parent.outputs[5] = 1
    simulation.config.world.max_population = 1
    before = parent.energy
    assert simulation.reproduction.attempt(parent, 0) == (None, "population_limit")
    assert parent.energy == before
    simulation.config.world.max_population = 0
    parent.position[:] = [-100, -100]  # all candidate positions are invalid
    assert simulation.reproduction.attempt(parent, 0) == (None, "placement_blocked")
    assert parent.energy == before


def test_capacity_event_and_no_population_selection():
    simulation, parent = reproductive_simulation()
    simulation.config.world.max_population = 1
    simulation.step()
    assert list(simulation.world.organisms) == [parent.id]
    assert simulation.population_limit_hits == 1
    assert any(e["kind"] == "population_limit" for e in simulation.events)


def test_plasticity_bounded_disabled_and_not_inherited():
    config = Configuration()
    rng = np.random.default_rng(7)
    genome = Genome.initial(config.neural, rng)
    signature = genome.signature()
    brain = Brain(genome, config.neural)
    for _ in range(500):
        brain.forward(np.ones(16))
        brain.learn(0.5)
    assert np.any(brain.acquired != 0)
    assert np.max(np.abs(brain.acquired)) <= config.neural.plastic_bound
    assert genome.signature() == signature
    child = genome.mutated(config.neural, np.random.default_rng(8))
    assert np.all(Brain(child, config.neural).acquired == 0)
    config.neural.plasticity = False
    frozen = brain.acquired.copy()
    brain.learn(10)
    np.testing.assert_array_equal(frozen, brain.acquired)


def test_mutations_disabled_and_parameter_mutation():
    config = Configuration()
    genome = Genome.initial(config.neural, np.random.default_rng(1))
    config.neural.mutations = False
    child = genome.mutated(config.neural, np.random.default_rng(3))
    assert child is not genome
    assert child.signature() == genome.signature()
    config.neural.mutations = True
    config.neural.weight_mutation_probability = 1
    config.neural.bias_mutation_probability = 1
    assert genome.mutated(config.neural, np.random.default_rng(3)).signature() != genome.signature()


def test_actual_offspring_does_not_inherit_parent_acquired_weights():
    config = Configuration()
    config.world.initial_population = 1
    config.body.initial_energy = 200
    config.neural.mutations = False
    simulation = Simulation(config)
    parent = simulation.world.organisms[1]
    parent.brain.acquired[:] = 0.4
    parent.outputs[5] = 1
    child, blocked = simulation.reproduction.attempt(parent, 1)
    assert child is not None and blocked is None
    np.testing.assert_array_equal(child.brain.inherited_weights, parent.brain.inherited_weights)
    assert np.all(child.brain.acquired == 0)


def test_genetic_distance_ignores_lifetime_learning():
    config = Configuration()
    genome = Genome.initial(config.neural, np.random.default_rng(12))
    clone = genome.clone()
    assert genome.distance(clone, config.neural.parameter_bound) == 0
    brain = Brain(clone, config.neural)
    brain.acquired[:] = 0.4
    assert genome.distance(clone, config.neural.parameter_bound) == 0
    clone.connections[0].weight += 0.1
    assert genome.distance(clone, config.neural.parameter_bound) > 0


@pytest.mark.parametrize(
    "operation", ["add_node", "remove_node", "add_connection", "remove_connection"]
)
def test_each_structural_mutation(operation):
    config = Configuration()
    n = config.neural
    for name in ("add_node", "remove_node", "add_connection", "remove_connection"):
        setattr(n, name + "_probability", float(name == operation))
    n.weight_mutation_probability = n.bias_mutation_probability = 0
    genome = Genome.initial(n, np.random.default_rng(4))
    child = genome.mutated(n, np.random.default_rng(9))
    child.validate(n)
    if operation == "add_node":
        assert len(child.nodes) == len(genome.nodes) + 1
        assert len(child.connections) == len(genome.connections) + 1
    elif operation == "remove_node":
        assert len(child.nodes) == len(genome.nodes) - 1
    elif operation == "add_connection":
        assert len(child.connections) == len(genome.connections) + 1
    else:
        assert len(child.connections) == len(genome.connections) - 1


def test_many_mutations_preserve_integrity_and_finite_inference():
    config = Configuration()
    n = config.neural
    n.add_node_probability = n.add_connection_probability = 0.8
    n.remove_node_probability = n.remove_connection_probability = 0.4
    n.max_nodes = 38
    n.max_connections = 190
    rng = np.random.default_rng(321)
    genome = Genome.initial(n, rng)
    for _ in range(500):
        genome = genome.mutated(n, rng)
        genome.validate(n)
        output = Brain(genome, n).forward(rng.random(16))
        assert np.all(np.isfinite(output))
        assert len(genome.nodes) <= n.max_nodes
        assert len(genome.connections) <= n.max_connections


def test_graph_rejects_cycles_dangling_and_nan():
    config = Configuration()
    genome = Genome.initial(config.neural, np.random.default_rng(1))
    broken = genome.clone()
    broken.connections.append(Connection(22, 22, 0.1))
    with pytest.raises(ValueError, match="cycle"):
        broken.validate(config.neural)
    broken = genome.clone()
    broken.connections.append(Connection(999, 22, 0.1))
    with pytest.raises(ValueError, match="absent"):
        broken.validate(config.neural)
    broken = genome.clone()
    broken.connections[0].weight = float("nan")
    with pytest.raises(ValueError, match="parameter"):
        broken.validate(config.neural)


def test_diagnostic_birth_uses_random_network_outputs():
    config = Configuration.load(Path("configs/diagnostic.toml"))
    simulation = Simulation(config, seed=42)
    simulation.step()
    assert simulation.births > 0
    parents = [o for o in simulation.world.organisms.values() if o.offspring]
    assert all(o.outputs[5] >= config.reproduction.threshold for o in parents)
    assert simulation.world.energy_balance_error() == pytest.approx(0, abs=1e-8)
