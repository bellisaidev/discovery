"""Fixed-tick orchestration. Views and observers cannot affect controller randomness."""

import math
from dataclasses import asdict

import numpy as np

from .brain import Action, Brain
from .configuration import Configuration
from .genome import Genome
from .organism import Organism
from .physics import Physics
from .reproduction import Reproduction
from .sensors import Sensors
from .signals import SignalField
from .world import World


class Simulation:
    def __init__(self, config: Configuration | None = None, seed: int = 42):
        self.config = config or Configuration()
        self.config.validate()
        if seed < 0 or seed >= 2**63:
            raise ValueError("Seed must be between 0 and 2**63 - 1")
        self.seed = seed
        world_seed, body_seed, gene_seed, placement_seed, mutation_seed = np.random.SeedSequence(
            seed
        ).spawn(5)
        self.world = World(self.config, np.random.default_rng(world_seed))
        body_rng, gene_rng = np.random.default_rng(body_seed), np.random.default_rng(gene_seed)
        base = Genome.initial(self.config.neural, gene_rng)
        b, w = self.config.body, self.config.world
        for identifier in range(1, w.initial_population + 1):
            for _ in range(10000):
                position = body_rng.uniform(
                    [b.radius, b.radius], [w.width - b.radius, w.height - b.radius]
                )
                if self.world.valid_body_position(position, b.radius):
                    break
            else:
                raise ValueError("Cannot place initial population without overlapping bodies")
            genome = base.clone()
            genome.perturb_initial(self.config.neural, gene_rng)
            organism = Organism(
                identifier,
                position,
                float(body_rng.uniform(0, math.tau)),
                b.initial_energy,
                genome,
                Brain(genome, self.config.neural),
                lineage_id=identifier,
                radius=b.radius,
                mass=b.mass,
            )
            self.world.organisms[identifier] = organism
        self.world.rebuild_body_index()
        self.world.ledger.initial = self.world.total_energy()
        self.physics = Physics(self.world)
        self.sensors = Sensors(self.world)
        self.signals = SignalField(self.config) if self.config.signals.enabled else None
        self.reproduction = Reproduction(
            self.world, np.random.default_rng(placement_seed), mutation_seed
        )
        self.tick = 0
        self.events = []
        self.births = 0
        self.deaths = 0
        self.contacts = 0
        self.population_limit_hits = 0
        self.records = {}
        for organism in self.world.organisms.values():
            self._record_birth(organism, initial=True)

    def _record_birth(self, organism: Organism, initial: bool = False) -> None:
        self.records[organism.id] = {
            "id": organism.id,
            "parent_id": organism.parent_id,
            "lineage_id": organism.lineage_id,
            "generation": organism.generation,
            "born_tick": organism.born_tick,
            "death_tick": None,
            "death_cause": None,
            "lifespan": None,
            "acquired_energy": 0.0,
            "offspring": 0,
            "descendants": 0,
            "neurons": len(organism.genome.nodes),
            "connections": len(organism.genome.connections),
            "genome_signature": organism.genome.signature(),
        }
        if not initial:
            self.births += 1
            self.events.append(
                {
                    "tick": self.tick,
                    "kind": "birth",
                    "organism_id": organism.id,
                    "parent_id": organism.parent_id,
                }
            )
            ancestor = organism.parent_id
            while ancestor is not None:
                self.records[ancestor]["descendants"] += 1
                ancestor = self.records[ancestor]["parent_id"]

    def _die(self, organism: Organism, cause: str) -> None:
        self.world.ledger.dissipate(organism.energy, "death")
        organism.energy = 0.0
        record = self.records[organism.id]
        record.update(
            death_tick=self.tick,
            death_cause=cause,
            lifespan=organism.age,
            acquired_energy=organism.acquired_energy,
            offspring=organism.offspring,
        )
        del self.world.organisms[organism.id]
        self.deaths += 1
        self.events.append(
            {
                "tick": self.tick,
                "kind": "death",
                "organism_id": organism.id,
                "cause": cause,
                "lifespan": organism.age,
            }
        )

    def step(self) -> None:
        self.tick += 1
        dt, b = self.config.world.dt, self.config.body
        for organism in list(self.world.organisms.values()):
            organism.age += dt
            cost = min(organism.energy, b.metabolism * dt)
            organism.energy -= cost
            self.world.ledger.dissipate(cost, "metabolic")
            if organism.energy <= 0:
                self._die(organism, "energy_exhaustion")
            elif b.max_age and organism.age >= b.max_age:
                self._die(organism, "age_limit")
        self.world.rebuild_body_index()
        actions = {}
        for identifier, organism in sorted(self.world.organisms.items()):
            organism.sensors = self.sensors.read(organism, self.signals)
            organism.outputs = organism.brain.forward(organism.sensors)
            actions[identifier] = Action.from_array(organism.outputs)
            organism.brain.learn(dt)
        emissions = self.physics.advance(actions)
        self.contacts += self.physics.contacts
        for organism in list(self.world.organisms.values()):
            if organism.energy <= 0:
                self._die(organism, "energy_exhaustion")
        for organism in list(self.world.organisms.values()):
            child, blocked = self.reproduction.attempt(organism, self.tick)
            if child:
                self._record_birth(child)
            elif blocked:
                self.events.append({"tick": self.tick, "kind": blocked, "organism_id": organism.id})
                self.population_limit_hits += blocked == "population_limit"
        self.world.regenerate()
        if self.signals is not None:
            self.signals.advance(emissions)
        self.world.rebuild_body_index()

    def snapshot(self) -> dict:
        """Detached numerical data. It contains no mutable references into the engine."""
        organisms = []
        for organism in self.world.organisms.values():
            organisms.append(
                {
                    "id": organism.id,
                    "parent_id": organism.parent_id,
                    "lineage_id": organism.lineage_id,
                    "generation": organism.generation,
                    "position": organism.position.copy(),
                    "velocity": organism.velocity.copy(),
                    "orientation": organism.orientation,
                    "radius": organism.radius,
                    "energy": organism.energy,
                    "age": organism.age,
                    "neurons": len(organism.genome.nodes),
                    "connections": len(organism.genome.connections),
                    "sensors": organism.sensors.copy(),
                    "outputs": organism.outputs.copy(),
                    "acquired_energy": organism.acquired_energy,
                    "offspring": organism.offspring,
                }
            )
        return {
            "tick": self.tick,
            "time": self.tick * self.config.world.dt,
            "organisms": organisms,
            "resource_positions": self.world.resource_positions.copy(),
            "resource_energy": self.world.resource_energy.copy(),
            "signals": None if self.signals is None else self.signals.field.copy(),
            "ledger": asdict(self.world.ledger),
            "energy_error": self.world.energy_balance_error(),
        }

    def state_fingerprint(self) -> str:
        """Canonical complete dynamic state for reproducibility checks (excluding observations)."""
        import hashlib
        import json

        digest = hashlib.sha256()
        digest.update(str(self.tick).encode())
        for identifier, organism in sorted(self.world.organisms.items()):
            digest.update(
                str(
                    (
                        identifier,
                        organism.parent_id,
                        organism.lineage_id,
                        organism.generation,
                        organism.energy,
                        organism.age,
                        organism.orientation,
                        organism.last_birth_age,
                    )
                ).encode()
            )
            for array in (
                organism.position,
                organism.velocity,
                organism.brain.acquired,
                organism.brain.activities,
                organism.sensors,
                organism.outputs,
            ):
                digest.update(array.tobytes())
            digest.update(organism.genome.signature().encode())
        digest.update(self.world.resource_energy.tobytes())
        if self.signals:
            digest.update(self.signals.field.tobytes())
            for tick, identifiers, xs, ys, amplitudes in self.signals.history:
                digest.update(str(tick).encode())
                for array in (identifiers, xs, ys, amplitudes):
                    digest.update(array.tobytes())
        digest.update(
            json.dumps(self.reproduction.placement_rng.bit_generator.state, sort_keys=True).encode()
        )
        digest.update(str(self.reproduction.next_id).encode())
        return digest.hexdigest()
