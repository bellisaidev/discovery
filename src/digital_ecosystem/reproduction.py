"""Physical asexual reproduction; no score, ranking, or learnt-weight inheritance."""

import math

import numpy as np

from .brain import Brain
from .organism import Organism
from .world import World


class Reproduction:
    def __init__(
        self,
        world: World,
        placement_rng: np.random.Generator,
        mutation_seed: np.random.SeedSequence,
    ):
        self.world = world
        self.placement_rng = placement_rng
        self.mutation_seed = mutation_seed
        self.next_id = world.config.world.initial_population + 1

    def attempt(self, parent: Organism, tick: int) -> tuple[Organism | None, str | None]:
        config, world = self.world.config, self.world
        r, b = config.reproduction, config.body
        if parent.outputs[5] < r.threshold or parent.age - parent.last_birth_age < r.cooldown:
            return None, None
        required = max(r.minimum_energy, r.offspring_energy + r.cost + r.reserve)
        if parent.energy < required:
            return None, None
        if config.world.max_population and len(world.organisms) >= config.world.max_population:
            return None, "population_limit"
        position = None
        for _ in range(r.placement_attempts):
            angle = self.placement_rng.uniform(0, math.tau)
            candidate = parent.position + (parent.radius + b.radius + 0.1) * np.array(
                [math.cos(angle), math.sin(angle)]
            )
            if world.valid_body_position(candidate, b.radius):
                position = candidate
                break
        if position is None:
            return None, "placement_blocked"
        identifier = self.next_id
        self.next_id += 1
        # Per-birth IDs isolate mutation randomness from placement and observations.
        seed = np.random.SeedSequence(
            self.mutation_seed.entropy, spawn_key=(*self.mutation_seed.spawn_key, identifier)
        )
        genome = parent.genome.mutated(config.neural, np.random.default_rng(seed))
        child = Organism(
            identifier,
            position,
            float(self.placement_rng.uniform(0, math.tau)),
            r.offspring_energy,
            genome,
            Brain(genome, config.neural),
            parent_id=parent.id,
            lineage_id=parent.lineage_id,
            generation=parent.generation + 1,
            radius=b.radius,
            mass=b.mass,
            born_tick=tick,
        )
        parent.energy -= r.offspring_energy + r.cost
        parent.offspring += 1
        parent.last_birth_age = parent.age
        world.ledger.inherited += r.offspring_energy
        world.ledger.dissipate(r.cost, "reproductive")
        world.organisms[identifier] = child
        return child, None
