"""Local geometry and energy consequences of numeric world actions."""

import math

import numpy as np

from .brain import Action
from .world import World


class Physics:
    def __init__(self, world: World):
        self.world = world
        self.contacts = 0

    def advance(self, actions: dict[int, Action]) -> list[tuple[int, np.ndarray, np.ndarray]]:
        world, config = self.world, self.world.config
        b, s, dt = config.body, config.signals, config.world.dt
        harvest_controls = {}
        emissions = []
        for identifier, organism in sorted(world.organisms.items()):
            action = actions[identifier]
            accel = action.acceleration * b.acceleration
            turn = action.rotation * b.turn_rate
            harvest = action.resource_contact
            signals = np.array([action.signal_0, action.signal_1]) if s.enabled else np.zeros(2)
            cost = dt * (
                b.movement_cost * accel**2
                + b.rotation_cost * abs(turn)
                + b.harvesting_cost * harvest
                + s.emission_cost * float(signals.sum())
            )
            scale = min(1.0, organism.energy / cost) if cost > 0 else 1.0
            paid = min(organism.energy, cost)
            organism.energy -= paid
            world.ledger.dissipate(paid, "action")
            accel *= math.sqrt(scale)
            turn *= scale
            harvest_controls[identifier] = harvest * scale
            organism.orientation = (organism.orientation + turn * dt) % math.tau
            direction = np.array([math.cos(organism.orientation), math.sin(organism.orientation)])
            organism.velocity += accel * direction / organism.mass * dt
            organism.velocity *= math.exp(-b.drag * dt)
            speed = float(np.linalg.norm(organism.velocity))
            if speed > b.max_speed:
                organism.velocity *= b.max_speed / speed
            organism.position += organism.velocity * dt
            self._walls(organism)
            if s.enabled:
                emissions.append(
                    (identifier, organism.position.copy(), signals * scale * s.emission_rate * dt)
                )
        self.resolve_collisions()
        emissions = [
            (identifier, world.organisms[identifier].position.copy(), amplitude)
            for identifier, _, amplitude in emissions
        ]
        self.harvest(harvest_controls)
        return emissions

    def _walls(self, organism) -> None:
        w = self.world.config.world
        for axis, maximum in enumerate((w.width, w.height)):
            low, high = organism.radius, maximum - organism.radius
            if organism.position[axis] < low:
                organism.position[axis] = low
                organism.velocity[axis] = max(0.0, organism.velocity[axis])
            elif organism.position[axis] > high:
                organism.position[axis] = high
                organism.velocity[axis] = min(0.0, organism.velocity[axis])

    def resolve_collisions(self) -> None:
        world = self.world
        contacts = set()
        max_radius = max((o.radius for o in world.organisms.values()), default=0)
        for _ in range(world.config.body.collision_iterations):
            world.rebuild_body_index()
            moved = False
            for identifier, a in sorted(world.organisms.items()):
                for other_id in world.nearby_bodies(a.position, a.radius + max_radius):
                    if other_id <= identifier:
                        continue
                    b = world.organisms[other_id]
                    delta = b.position - a.position
                    squared_distance = float(delta[0] ** 2 + delta[1] ** 2)
                    if squared_distance >= (a.radius + b.radius) ** 2:
                        continue
                    distance = math.sqrt(squared_distance)
                    penetration = a.radius + b.radius - distance
                    if penetration <= 1e-8:
                        continue
                    contacts.add((identifier, other_id))
                    normal = delta / distance if distance > 1e-12 else np.array([1.0, 0.0])
                    inv_a, inv_b = 1 / a.mass, 1 / b.mass
                    amount = penetration + 1e-8
                    free_a = self._free_translation(a, -normal)
                    free_b = self._free_translation(b, normal)
                    shift_a = min(free_a, amount * inv_a / (inv_a + inv_b))
                    shift_b = min(free_b, amount - shift_a)
                    shift_a = min(free_a, amount - shift_b)
                    a.position -= normal * shift_a
                    b.position += normal * shift_b
                    relative = float(np.dot(b.velocity - a.velocity, normal))
                    if relative < 0:
                        impulse = -relative / (inv_a + inv_b)
                        a.velocity -= impulse * inv_a * normal
                        b.velocity += impulse * inv_b * normal
                    self._walls(a)
                    self._walls(b)
                    moved = True
            if not moved:
                break
        world.rebuild_body_index()
        self.contacts = len(contacts)

    def _free_translation(self, organism, direction: np.ndarray) -> float:
        """Distance available along a contact normal before reaching a solid wall."""
        limits = []
        w = self.world.config.world
        for axis, maximum in enumerate((w.width, w.height)):
            if abs(direction[axis]) > 1e-12:
                wall = maximum - organism.radius if direction[axis] > 0 else organism.radius
                limits.append((wall - organism.position[axis]) / direction[axis])
        return max(0.0, min(limits, default=0.0))

    def harvest(self, controls: dict[int, float]) -> None:
        world = self.world
        requests: dict[int, list[tuple[int, float]]] = {}
        for identifier, o in sorted(world.organisms.items()):
            nearby = world.nearby_resources(
                o.position, o.radius + world.config.world.resource_radius
            )
            touching = [
                i
                for i in nearby
                if np.linalg.norm(o.position - world.resource_positions[i])
                <= o.radius + world.config.world.resource_radius
            ]
            if not touching:
                continue
            amount = (
                controls.get(identifier, 0.0)
                * world.config.body.harvesting_rate
                * world.config.world.dt
                / len(touching)
            )
            for i in touching:
                requests.setdefault(i, []).append((identifier, amount))
        for resource, demands in sorted(requests.items()):
            demands = [
                (
                    i,
                    min(
                        amount,
                        max(0, world.config.body.energy_capacity - world.organisms[i].energy),
                    ),
                )
                for i, amount in demands
            ]
            total = math.fsum(amount for _, amount in demands)
            ratio = min(1.0, world.resource_energy[resource] / total) if total > 0 else 0.0
            for identifier, amount in demands:
                world.transfer_resource(resource, world.organisms[identifier], amount * ratio)
