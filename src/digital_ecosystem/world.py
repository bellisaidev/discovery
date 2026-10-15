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
    def __init__(
        self,
        config: Configuration,
        rng: np.random.Generator,
        relocation_rng: np.random.Generator | None = None,
    ):
        self.config = config
        self.rng = rng
        self.relocation_rng = relocation_rng if relocation_rng is not None else rng
        w = config.world
        margin = w.resource_radius
        if margin * 2 >= min(w.width, w.height):
            raise ValueError("Resource radius does not fit in world")
        self.resource_positions = rng.uniform(
            [margin, margin], [w.width - margin, w.height - margin], (w.resource_count, 2)
        )
        self.resource_energy = np.full(w.resource_count, w.resource_capacity, dtype=float)
        self.resource_active = np.ones(w.resource_count, dtype=bool)
        self.organisms: dict[int, Organism] = {}
        self.ledger = EnergyLedger()
        cell_size = max(2 * config.body.radius, config.sensors.range)
        self.body_index = SpatialIndex(cell_size)
        self.resource_index = SpatialIndex(cell_size)
        self.rebuild_resource_index()

    def rebuild_body_index(self) -> None:
        self.body_index.rebuild([(i, o.position) for i, o in sorted(self.organisms.items())])

    def rebuild_resource_index(self) -> None:
        self.resource_index.rebuild(
            [(i, self.resource_positions[i]) for i in np.flatnonzero(self.resource_active)]
        )

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

    def valid_resource_position(
        self,
        position: np.ndarray,
        radius: float,
        clearance: float = 0.0,
        exclude_resource: int | None = None,
    ) -> bool:
        w = self.config.world
        bound_r = radius + clearance
        if not (
            bound_r <= position[0] <= w.width - bound_r
            and bound_r <= position[1] <= w.height - bound_r
        ):
            return False
        for o in self.organisms.values():
            if np.linalg.norm(position - o.position) < radius + o.radius + clearance + 1e-6:
                return False
        active_indices = np.flatnonzero(self.resource_active)
        if exclude_resource is not None:
            active_indices = active_indices[active_indices != exclude_resource]
        if len(active_indices):
            deltas = self.resource_positions[active_indices] - position
            dists_sq = np.sum(deltas**2, axis=1)
            min_dist = 2 * radius + clearance + 1e-6
            if np.any(dists_sq < min_dist**2):
                return False
        return True

    def transfer_resource(self, resource: int, organism: Organism, requested: float) -> float:
        if not self.resource_active[resource]:
            return 0.0
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

    def regenerate(self) -> list[dict]:
        events = []
        w = self.config.world
        if not w.resource_relocation:
            increments = np.minimum(
                w.resource_capacity - self.resource_energy, w.resource_regeneration * w.dt
            )
            self.resource_energy += increments
            self.ledger.regenerated += float(np.sum(increments))
            return events

        # Step 1: Detect newly depleted active resources
        depleted = False
        for i in np.flatnonzero(self.resource_active):
            if self.resource_energy[i] <= 1e-9:
                self.resource_active[i] = False
                depleted = True
                events.append(
                    {
                        "kind": "resource_depleted",
                        "resource_id": int(i),
                        "x": float(self.resource_positions[i, 0]),
                        "y": float(self.resource_positions[i, 1]),
                        "residual_energy": float(self.resource_energy[i]),
                    }
                )

        # Step 2: Attempt respawn for inactive resources
        margin = w.resource_radius + w.resource_relocation_clearance
        reappeared = False
        for i in np.flatnonzero(~self.resource_active):
            prev_x, prev_y = float(self.resource_positions[i, 0]), float(
                self.resource_positions[i, 1]
            )
            for _ in range(w.resource_relocation_attempts):
                candidate = self.relocation_rng.uniform(
                    [margin, margin], [w.width - margin, w.height - margin]
                )
                if self.valid_resource_position(
                    candidate,
                    w.resource_radius,
                    w.resource_relocation_clearance,
                    exclude_resource=i,
                ):
                    self.resource_positions[i] = candidate
                    residual = float(self.resource_energy[i])
                    added = max(0.0, w.resource_capacity - residual)
                    self.resource_energy[i] = w.resource_capacity
                    self.resource_active[i] = True
                    self.ledger.regenerated += added
                    reappeared = True
                    events.append(
                        {
                            "kind": "resource_reappeared",
                            "resource_id": int(i),
                            "prev_x": prev_x,
                            "prev_y": prev_y,
                            "new_x": float(candidate[0]),
                            "new_y": float(candidate[1]),
                            "energy_before": residual,
                            "energy_added": added,
                            "capacity": float(w.resource_capacity),
                        }
                    )
                    break

        if depleted or reappeared:
            self.rebuild_resource_index()

        return events

    def total_energy(self) -> float:
        return float(np.sum(self.resource_energy)) + math.fsum(
            o.energy for o in self.organisms.values()
        )

    def energy_balance_error(self) -> float:
        return self.total_energy() - (
            self.ledger.initial + self.ledger.regenerated - self.ledger.dissipated
        )
