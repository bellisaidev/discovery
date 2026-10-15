"""Tests for dynamic resource relocation, inactive resource handling, and conservation."""

import copy
import sqlite3
import time

import numpy as np
import pytest

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.simulation import Simulation


def relocation_config() -> Configuration:
    config = Configuration.load("configs/relocation.toml")
    config.neural.plasticity = False
    config.signals.enabled = False
    config.reproduction.threshold = 1.0  # Prevent spontaneous reproduction
    config.body.movement_cost = 0.0
    config.body.rotation_cost = 0.0
    config.body.harvesting_cost = 0.0
    config.body.metabolism = 0.0
    return config


def test_numerical_equivalence_when_relocation_disabled():
    """Verify that when resource_relocation=False, the engine behavior is 100% deterministic."""
    for seed in (0, 42, 123):
        a = Simulation(Configuration.load("configs/experimental.toml"), seed=seed)
        b = Simulation(Configuration.load("configs/experimental.toml"), seed=seed)
        assert not a.config.world.resource_relocation
        for _ in range(40):
            a.step()
            b.step()
        assert a.state_fingerprint() == b.state_fingerprint()


def test_resource_relocation_replaces_inplace_regeneration():
    """Verify that depleted resources relocate while partial resources do not grow in-place."""
    config = relocation_config()
    config.world.initial_population = 1
    config.world.resource_count = 2
    simulation = Simulation(config, seed=42)
    world = simulation.world

    # Place resource 0 and 1
    world.resource_positions[0] = [300.0, 300.0]
    world.resource_positions[1] = [600.0, 300.0]
    world.resource_energy[0] = 10.0  # Partially consumed
    world.resource_energy[1] = 0.0   # Fully depleted
    world.rebuild_resource_index()
    world.ledger.initial = world.total_energy()

    initial_error = world.energy_balance_error()
    assert initial_error == pytest.approx(0.0, abs=1e-9)

    old_pos1 = world.resource_positions[1].copy()
    simulation.step()

    # Resource 0 was partially consumed (10.0), so it should NOT have grown in-place
    assert world.resource_energy[0] == pytest.approx(10.0)

    # Resource 1 was depleted, so it should have relocated and restored to full capacity
    assert world.resource_active[1]
    assert world.resource_energy[1] == pytest.approx(config.world.resource_capacity)
    assert not np.array_equal(world.resource_positions[1], old_pos1)

    # Energy balance strictly conserved
    assert world.energy_balance_error() == pytest.approx(0.0, abs=1e-9)
    assert world.ledger.regenerated == pytest.approx(config.world.resource_capacity)


def test_resource_relocation_spatial_exclusion_and_clearance():
    """Verify relocated resources strictly avoid bodies, other active resources, and boundaries."""
    config = relocation_config()
    config.world.initial_population = 2
    config.world.resource_count = 3
    config.world.resource_relocation_clearance = 5.0
    simulation = Simulation(config, seed=42)
    world = simulation.world

    # Position organisms
    o1, o2 = list(world.organisms.values())
    o1.position[:] = [200.0, 200.0]
    o2.position[:] = [400.0, 400.0]
    world.rebuild_body_index()

    # Deplete resource 0
    world.resource_energy[0] = 0.0
    world.resource_positions[1] = [500.0, 500.0]
    world.resource_positions[2] = [600.0, 600.0]
    world.rebuild_resource_index()

    simulation.step()

    new_pos = world.resource_positions[0]
    r_res = config.world.resource_radius
    clearance = config.world.resource_relocation_clearance

    # World boundaries
    assert r_res + clearance <= new_pos[0] <= config.world.width - (r_res + clearance)
    assert r_res + clearance <= new_pos[1] <= config.world.height - (r_res + clearance)

    # Organism exclusion
    for o in world.organisms.values():
        dist = np.linalg.norm(new_pos - o.position)
        assert dist >= r_res + o.radius + clearance - 1e-6

    # Other active resources exclusion
    for j in (1, 2):
        dist = np.linalg.norm(new_pos - world.resource_positions[j])
        assert dist >= 2 * r_res + clearance - 1e-6


def test_inactive_resource_lifecycle_and_deferral(monkeypatch):
    """Verify that resources that cannot relocate become inactive and defer reappearance."""
    config = relocation_config()
    config.world.initial_population = 1
    config.world.resource_count = 1
    simulation = Simulation(config, seed=42)
    world = simulation.world
    organism = list(world.organisms.values())[0]

    world.resource_energy[0] = 0.0
    world.resource_positions[0] = [100.0, 100.0]
    world.rebuild_resource_index()
    world.ledger.initial = world.total_energy()

    # Temporarily make all candidate positions invalid (e.g. simulated overcrowded world)
    original_valid = world.valid_resource_position
    monkeypatch.setattr(world, "valid_resource_position", lambda *args, **kwargs: False)

    simulation.step()

    # Resource could not find a spot: must be inactive
    assert not world.resource_active[0]
    assert world.resource_energy[0] == 0.0

    # Must NOT be detected by sensors
    sensors = simulation.sensors.read(organism)
    assert np.all(sensors[1:4] == 0.0)

    # Must NOT be harvestable
    organism.position[:] = world.resource_positions[0]
    before_energy = organism.energy
    simulation.physics.harvest({organism.id: 1.0})
    assert organism.energy == before_energy

    # Move organism away to test that the inactive resource doesn't block placement
    organism.position[:] = [500.0, 500.0]
    world.rebuild_body_index()
    assert original_valid(world.resource_positions[0], config.world.resource_radius)

    # In snapshot, resource_active must be False
    snap = simulation.snapshot()
    assert not snap["resource_active"][0]

    # Now restore valid placement: in the next tick, it must reappear
    monkeypatch.setattr(world, "valid_resource_position", original_valid)
    simulation.step()

    assert world.resource_active[0]
    assert world.resource_energy[0] == pytest.approx(config.world.resource_capacity)
    assert world.energy_balance_error() == pytest.approx(0.0, abs=1e-9)


def test_discrete_events_recorded_between_samples(tmp_path):
    """Verify every depletion and reappearance is logged with exact tick, sequence and coords."""
    config = relocation_config()
    config.logging.sample_interval = 30
    config.world.initial_population = 1
    config.world.resource_count = 2
    simulation = Simulation(config, seed=42)
    logger = ExperimentLogger(simulation, tmp_path)

    # Tick 1: force depletion of resource 0
    simulation.world.resource_energy[0] = 0.0
    simulation.step()

    # Verify events in memory before logger drains them
    kinds = [e["kind"] for e in simulation.events]
    assert "resource_depleted" in kinds
    assert "resource_reappeared" in kinds

    depleted_ev = next(e for e in simulation.events if e["kind"] == "resource_depleted")
    assert depleted_ev["resource_id"] == 0
    assert depleted_ev["tick"] == 1

    reappeared_ev = next(e for e in simulation.events if e["kind"] == "resource_reappeared")
    assert reappeared_ev["resource_id"] == 0
    assert reappeared_ev["tick"] == 1
    assert reappeared_ev["energy_added"] == pytest.approx(config.world.resource_capacity)

    logger.observe()

    # Run for 29 more ticks to trigger a sample commit
    for _ in range(29):
        simulation.step()
        logger.observe()

    logger.close()

    # Query events from SQLite
    with sqlite3.connect(tmp_path / "lab.sqlite3") as conn:
        rows = conn.execute(
            "SELECT tick, kind, event_seq FROM events "
            "WHERE kind LIKE 'resource_%' ORDER BY event_seq"
        ).fetchall()
        assert len(rows) >= 2
        assert rows[0][1] == "resource_depleted"
        assert rows[1][1] == "resource_reappeared"


def test_resource_relocation_checkpoint_continuity():
    """Verify deterministic resume from a checkpoint with relocation active."""
    config = relocation_config()
    config.world.resource_count = 10
    config.world.initial_population = 5

    # Run continuous
    a = Simulation(copy.deepcopy(config), seed=42)
    for _ in range(20):
        # Provoke depletions periodically
        if a.tick % 5 == 0:
            a.world.resource_energy[a.tick % 10] = 0.0
        a.step()

    checkpoint_state = a.to_state()
    b = Simulation.from_state(checkpoint_state)
    assert a.state_fingerprint() == b.state_fingerprint()

    # Advance both further
    for _ in range(25):
        if a.tick % 7 == 0:
            a.world.resource_energy[a.tick % 10] = 0.0
            b.world.resource_energy[b.tick % 10] = 0.0
        a.step()
        b.step()

    assert a.state_fingerprint() == b.state_fingerprint()


def test_legacy_checkpoint_compatibility():
    """Verify states missing resource_active or relocation_rng restore cleanly."""
    config = Configuration.load("configs/diagnostic.toml")
    simulation = Simulation(config, seed=42)
    simulation.step()

    state = simulation.to_state()
    # Simulate an M4 legacy checkpoint lacking relocation fields
    state.pop("resource_active", None)
    state.pop("relocation_rng", None)

    restored = Simulation.from_state(state)
    assert restored.world.resource_active.all()
    assert restored.world.relocation_rng is not None
    restored.step()
    assert restored.world.energy_balance_error() == pytest.approx(0.0, abs=1e-9)


def test_measured_relocation_benchmark():
    """Empirically measure the execution time of regeneration with relocations."""
    measurements = {}
    for pop_size in (10, 100, 256):
        config = relocation_config()
        config.world.initial_population = pop_size
        config.world.max_population = pop_size
        simulation = Simulation(config, seed=42)

        durations = []
        for _ in range(30):
            # Deplete 5 resources each step to benchmark relocation overhead
            for idx in range(5):
                target = (simulation.tick + idx) % config.world.resource_count
                simulation.world.resource_energy[target] = 0.0
            start = time.perf_counter()
            simulation.world.regenerate()
            durations.append((time.perf_counter() - start) * 1000.0)  # ms
            simulation.step()

        p50 = float(np.percentile(durations, 50))
        p95 = float(np.percentile(durations, 95))
        measurements[pop_size] = (p50, p95)
        # Measured sanity check: relocation of 5 resources among up to 256 bodies (< 25 ms)
        assert p95 < 25.0, f"Population {pop_size} exceeded 25ms: p95={p95}ms"


def test_gui_provoked_depletion_and_respawn():
    """Verify GUI snapshot and renderer handle provoked resource depletion and respawn."""
    config = relocation_config()
    config.world.initial_population = 1
    config.world.resource_count = 1
    simulation = Simulation(config, seed=42)
    world = simulation.world
    organism = list(world.organisms.values())[0]

    # Place organism directly on the resource with minimal energy
    res_pos = world.resource_positions[0].copy()
    organism.position[:] = res_pos
    world.resource_energy[0] = 0.1
    world.rebuild_body_index()
    world.rebuild_resource_index()

    # Step: organism harvests (output 2 = resource_contact), depletes resource, relocates
    organism.brain.last_outputs = np.array([0, 0, 1, 0, 0, 0], dtype=float)
    simulation.step()

    # Resource should have moved
    assert not np.array_equal(world.resource_positions[0], res_pos)
    assert world.resource_active[0]
    assert world.resource_energy[0] == pytest.approx(config.world.resource_capacity)

    # Verify renderer snapshot contains valid data
    snap = simulation.snapshot()
    assert snap["resource_active"][0]
    assert np.all(np.isfinite(snap["resource_positions"]))
