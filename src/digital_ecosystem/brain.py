"""Numerical controller: sensor arrays in, physical controls out. No world access."""

from dataclasses import dataclass

import numpy as np

from .configuration import NeuralConfig
from .genome import Genome

OUTPUT_NAMES = (
    "acceleration",
    "rotation",
    "resource_contact",
    "signal_0",
    "signal_1",
    "reproduction",
)


@dataclass(frozen=True)
class Action:
    acceleration: float
    rotation: float
    resource_contact: float
    signal_0: float
    signal_1: float
    reproduction: float

    @classmethod
    def from_array(cls, values: np.ndarray) -> "Action":
        if values.shape != (6,) or not np.all(np.isfinite(values)):
            raise ValueError("Invalid physical action")
        return cls(
            max(-1.0, min(1.0, float(values[0]))),
            max(-1.0, min(1.0, float(values[1]))),
            *(max(0.0, min(1.0, float(v))) for v in values[2:]),
        )


class Brain:
    def __init__(self, genome: Genome, config: NeuralConfig):
        genome.validate(config)
        ids = sorted(genome.nodes)
        mapping = {i: j for j, i in enumerate(ids)}
        self.config = config
        self.activities = np.zeros(len(ids), dtype=np.float64)
        self.input_indices = np.array([mapping[i] for i in range(16)])
        self.output_indices = np.array([mapping[i] for i in range(16, 22)])
        self.biases = np.array([genome.nodes[i].bias for i in ids])
        self.sources = np.array([mapping[e.source] for e in genome.connections], dtype=np.intp)
        self.targets = np.array([mapping[e.target] for e in genome.connections], dtype=np.intp)
        self.inherited_weights = np.array([e.weight for e in genome.connections])
        self.acquired = np.zeros_like(self.inherited_weights)
        depth = {}
        incoming = {i: [] for i in ids}
        for edge in genome.connections:
            incoming[edge.target].append(edge.source)
        for i in genome.topological_order():
            depth[i] = (
                0
                if genome.nodes[i].kind == "input"
                else 1 + max((depth[j] for j in incoming[i]), default=0)
            )
        self.layers = []
        for d in sorted(set(depth.values()) - {0}):
            indices = np.array([mapping[i] for i in ids if depth[i] == d])
            edge_indices = np.flatnonzero(np.isin(self.targets, indices))
            self.layers.append((indices, edge_indices))
        self.last_outputs = np.zeros(6)

    def forward(self, sensors: np.ndarray) -> np.ndarray:
        if sensors.shape != (16,) or not np.all(np.isfinite(sensors)):
            raise ValueError("Invalid sensor array")
        self.activities.fill(0)
        self.activities[self.input_indices] = np.clip(sensors, 0, 1)
        weights = np.clip(
            self.inherited_weights + self.acquired,
            -self.config.parameter_bound,
            self.config.parameter_bound,
        )
        for indices, edges in self.layers:
            total = np.bincount(
                self.targets[edges],
                weights=weights[edges] * self.activities[self.sources[edges]],
                minlength=len(self.activities),
            )
            self.activities[indices] = np.tanh(total[indices] + self.biases[indices])
        outputs = self.activities[self.output_indices].copy()
        outputs[2:] = (outputs[2:] + 1) / 2
        self.last_outputs = outputs
        return outputs.copy()

    def learn(self, dt: float) -> None:
        if self.config.plasticity:
            activity = self.activities[self.sources] * self.activities[self.targets]
            self.acquired += dt * (
                self.config.learning_rate * activity - self.config.plastic_decay * self.acquired
            )
            np.clip(
                self.acquired,
                -self.config.plastic_bound,
                self.config.plastic_bound,
                out=self.acquired,
            )
