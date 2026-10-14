"""A numerical body and its heritable and lifetime states."""

from dataclasses import dataclass, field

import numpy as np

from .brain import Brain
from .genome import Genome


@dataclass
class Organism:
    id: int
    position: np.ndarray
    orientation: float
    energy: float
    genome: Genome
    brain: Brain
    parent_id: int | None = None
    lineage_id: int = 0
    generation: int = 0
    age: float = 0.0
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(2))
    radius: float = 6.0
    mass: float = 1.0
    born_tick: int = 0
    last_birth_age: float = -1e30
    acquired_energy: float = 0.0
    offspring: int = 0
    sensors: np.ndarray = field(default_factory=lambda: np.zeros(16))
    outputs: np.ndarray = field(default_factory=lambda: np.zeros(6))
