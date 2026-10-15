"""Local, body-oriented observations; no identity, genotype or remote state inputs."""

import math

import numpy as np

from .world import World

SECTOR_OFFSETS = np.array([0.0, math.pi / 2, -math.pi / 2])
SENSOR_NAMES = (
    "energy",
    "resource_front",
    "resource_left",
    "resource_right",
    "body_front",
    "body_left",
    "body_right",
    "wall_front",
    "wall_left",
    "wall_right",
    "signal0_front",
    "signal0_left",
    "signal0_right",
    "signal1_front",
    "signal1_left",
    "signal1_right",
)


class Sensors:
    def __init__(self, world: World):
        self.world = world

    def read(self, organism, signals=None) -> np.ndarray:
        world, sensor = self.world, self.world.config.sensors
        radius = sensor.range
        result = np.zeros(16)
        result[0] = organism.energy / world.config.body.energy_capacity
        directions = organism.orientation + SECTOR_OFFSETS
        resources = [
            i for i in world.nearby_resources(organism.position, radius) if world.resource_active[i]
        ]
        if resources:
            delta = world.resource_positions[resources] - organism.position
            distances = np.linalg.norm(delta, axis=1)
            angles = np.arctan2(delta[:, 1], delta[:, 0])
            strength = np.maximum(0, 1 - distances / radius) * (
                world.resource_energy[resources] / world.config.world.resource_capacity
            )
            for j, angle in enumerate(directions):
                difference = np.abs((angles - angle + math.pi) % math.tau - math.pi)
                result[1 + j] = np.max(
                    np.where(difference <= sensor.sector_half_angle, strength, 0), initial=0
                )
        others = [i for i in world.nearby_bodies(organism.position, radius) if i != organism.id]
        if others:
            delta = np.array([world.organisms[i].position for i in others]) - organism.position
            distances = np.linalg.norm(delta, axis=1)
            angles = np.arctan2(delta[:, 1], delta[:, 0])
            differences = np.abs(
                (angles[None, :] - directions[:, None] + math.pi) % math.tau - math.pi
            )
            strengths = np.maximum(0, 1 - distances / radius)
            result[4:7] = np.max(
                np.where(differences <= sensor.sector_half_angle, strengths[None, :], 0),
                axis=1,
                initial=0,
            )
        w = world.config.world
        for j, angle in enumerate(directions):
            dx, dy = math.cos(angle), math.sin(angle)
            distances = []
            if abs(dx) > 1e-10:
                wall = w.width - organism.radius if dx > 0 else organism.radius
                distances.append((wall - organism.position[0]) / dx)
            if abs(dy) > 1e-10:
                wall = w.height - organism.radius if dy > 0 else organism.radius
                distances.append((wall - organism.position[1]) / dy)
            distance = max(0.0, min(distances, default=radius))
            result[7 + j] = max(0.0, 1 - distance / radius)
        if signals is not None and world.config.signals.enabled:
            probes = organism.position + radius * 0.5 * np.column_stack(
                (np.cos(directions), np.sin(directions))
            )
            sensed = signals.sample(probes, exclude=organism.id)
            result[10:13] = sensed[:, 0] / world.config.signals.sensor_scale
            result[13:16] = sensed[:, 1] / world.config.signals.sensor_scale
        return np.clip(result, 0, 1)
