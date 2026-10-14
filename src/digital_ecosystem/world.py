"""World-owned geometry and energy storage. Future material interactions belong here."""

import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .configuration import Configuration
from .organism import Organism


@dataclass
class EnergyLedger:
    initial: float = 0.0
    regenerated: float = 0.0
    dissipated: float = 0.0
    harvested: float = 0.0
    inherited: float = 0.0
    metabolic_dissipation: float = 0.0
    action_dissipation: float = 0.0
    reproductive_dissipation: float = 0.0
    death_dissipation: float = 0.0

    def dissipate(self, amount: float, category: str) -> None:
        if amount < -1e-12 or not np.isfinite(amount):
            raise ValueError("Invalid energy dissipation")
        amount = max(0.0, amount)
        self.dissipated += amount
        attr = f"{category}_dissipation"
        setattr(self, attr, getattr(self, attr) + amount)


class SpatialIndex:
    def __init__(self, cell_size: float):
        self.cell_size = cell_size
        self.cells = defaultdict(list)

    def rebuild(self, positions: list[tuple[int, np.ndarray]]) -> None:
        self.cells.clear()
        for identifier, position in positions:
            key = (
                math.floor(position[0] / self.cell_size),
                math.floor(position[1] / self.cell_size),
            )
            self.cells[key].append(identifier)

    def query(self, position: np.ndarray, radius: float) -> list[int]:
        low = (
            math.floor((position[0] - radius) / self.cell_size),
            math.floor((position[1] - radius) / self.cell_size),
        )
        high = (
            math.floor((position[0] + radius) / self.cell_size),
            math.floor((position[1] + radius) / self.cell_size),
        )
        return sorted(
            identifier
            for x in range(low[0], high[0] + 1)
            for y in range(low[1], high[1] + 1)
            for identifier in self.cells.get((x, y), ())
        )


class World:
    def __init__(self, config: Configuration, rng: np.random.Generator):
        self.config = config
        w = config.world
        margin = w.resource_radius
        if margin * 2 >= min(w.width, w.height):
            raise ValueError("Resource radius does not fit in world")
        self.resource_positions = rng.uniform(
            [margin, margin], [w.width - margin, w.height - margin], (w.resource_count, 2)
        )
        self.resource_energy = np.full(w.resource_count, w.resource_capacity, dtype=float)
        self.organisms: dict[int, Organism] = {}
        self.ledger = EnergyLedger()
        cell_size = max(2 * config.body.radius, config.sensors.range)
        self.body_index = SpatialIndex(cell_size)
        self.resource_index = SpatialIndex(cell_size)
        self.resource_index.rebuild(list(enumerate(self.resource_positions)))

    def rebuild_body_index(self) -> None:
        self.body_index.rebuild([(i, o.position) for i, o in sorted(self.organisms.items())])

    def nearby_resources(self, position: np.ndarray, radius: float) -> list[int]:
        return self.resource_index.query(position, radius)

    def nearby_bodies(self, position: np.ndarray, radius: float) -> list[int]:
        return self.body_index.query(position, radius)

    def valid_body_position(self, position: np.ndarray, radius: float) -> bool:
        w = self.config.world
        if not (
            radius <= position[0] <= w.width - radius and radius <= position[1] <= w.height - radius
        ):
            return False
        return all(
            np.linalg.norm(position - o.position) >= radius + o.radius + 1e-6
            for o in self.organisms.values()
        )

    def transfer_resource(self, resource: int, organism: Organism, requested: float) -> float:
        amount = max(
            0.0,
            min(
                requested,
                self.resource_energy[resource],
                self.config.body.energy_capacity - organism.energy,
            ),
        )
        self.resource_energy[resource] -= amount
        organism.energy += amount
        organism.acquired_energy += amount
        self.ledger.harvested += amount
        return amount

    def regenerate(self) -> None:
        w = self.config.world
        increments = np.minimum(
            w.resource_capacity - self.resource_energy, w.resource_regeneration * w.dt
        )
        self.resource_energy += increments
        self.ledger.regenerated += float(np.sum(increments))

    def total_energy(self) -> float:
        return float(np.sum(self.resource_energy)) + math.fsum(
            o.energy for o in self.organisms.values()
        )

    def energy_balance_error(self) -> float:
        return self.total_energy() - (
            self.ledger.initial + self.ledger.regenerated - self.ledger.dissipated
        )
