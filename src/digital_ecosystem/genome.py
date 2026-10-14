"""Heritable DAG parameters. No lifetime learning or selection lives here."""

import hashlib
import heapq
import json
from dataclasses import dataclass

import numpy as np

from .configuration import NeuralConfig

INPUT_COUNT = 16
OUTPUT_COUNT = 6


@dataclass
class Node:
    id: int
    kind: str
    bias: float = 0.0


@dataclass
class Connection:
    source: int
    target: int
    weight: float


@dataclass
class Genome:
    nodes: dict[int, Node]
    connections: list[Connection]
    next_node_id: int

    @classmethod
    def initial(cls, config: NeuralConfig, rng: np.random.Generator) -> "Genome":
        nodes = {i: Node(i, "input") for i in range(INPUT_COUNT)}
        nodes.update({i: Node(i, "output") for i in range(INPUT_COUNT, 22)})
        hidden = list(range(22, 22 + config.hidden_neurons))
        nodes.update({i: Node(i, "hidden") for i in hidden})
        layers = [list(range(INPUT_COUNT)), hidden, list(range(INPUT_COUNT, 22))]
        if not hidden:
            layers.pop(1)
        connections = []
        for a, b in zip(layers[:-1], layers[1:], strict=True):
            for source in a:
                for target in b:
                    weight = float(rng.normal(0, config.initial_weight_std))
                    connections.append(
                        Connection(
                            source,
                            target,
                            float(np.clip(weight, -config.parameter_bound, config.parameter_bound)),
                        )
                    )
        return cls(nodes, connections, 22 + config.hidden_neurons)

    def clone(self) -> "Genome":
        return Genome(
            {i: Node(n.id, n.kind, n.bias) for i, n in self.nodes.items()},
            [Connection(e.source, e.target, e.weight) for e in self.connections],
            self.next_node_id,
        )

    def to_data(self) -> dict:
        """Lossless order-preserving genetic data, unlike the observational signature."""
        return {
            "nodes": [[n.id, n.kind, n.bias] for n in self.nodes.values()],
            "connections": [[e.source, e.target, e.weight] for e in self.connections],
            "next_node_id": self.next_node_id,
        }

    @classmethod
    def from_data(cls, data: dict, config: NeuralConfig) -> "Genome":
        nodes = [Node(*row) for row in data["nodes"]]
        if len({n.id for n in nodes}) != len(nodes):
            raise ValueError("Duplicate node IDs")
        genome = cls(
            {n.id: n for n in nodes},
            [Connection(*row) for row in data["connections"]],
            data["next_node_id"],
        )
        genome.validate(config)
        return genome

    def perturb_initial(self, config: NeuralConfig, rng: np.random.Generator) -> None:
        for edge in self.connections:
            edge.weight = float(
                np.clip(
                    edge.weight + rng.normal(0, config.initial_variation),
                    -config.parameter_bound,
                    config.parameter_bound,
                )
            )
        for node in self.nodes.values():
            if node.kind != "input":
                node.bias = float(
                    np.clip(
                        rng.normal(0, config.initial_variation),
                        -config.parameter_bound,
                        config.parameter_bound,
                    )
                )

    def topological_order(self) -> list[int]:
        incoming = dict.fromkeys(self.nodes, 0)
        outgoing = {i: [] for i in self.nodes}
        for edge in self.connections:
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError("Connection references an absent node")
            incoming[edge.target] += 1
            outgoing[edge.source].append(edge.target)
        queue = [i for i, degree in incoming.items() if degree == 0]
        heapq.heapify(queue)
        result = []
        while queue:
            i = heapq.heappop(queue)
            result.append(i)
            for target in sorted(outgoing[i]):
                incoming[target] -= 1
                if incoming[target] == 0:
                    heapq.heappush(queue, target)
        if len(result) != len(self.nodes):
            raise ValueError("Neural graph contains a cycle")
        return result

    def validate(self, config: NeuralConfig) -> None:
        if len(self.nodes) > config.max_nodes or len(self.connections) > config.max_connections:
            raise ValueError("Neural graph exceeds computational bounds")
        if sorted(i for i, n in self.nodes.items() if n.kind == "input") != list(range(16)):
            raise ValueError("Invalid sensory interface")
        if sorted(i for i, n in self.nodes.items() if n.kind == "output") != list(range(16, 22)):
            raise ValueError("Invalid motor interface")
        if any(
            n.id != i or n.kind not in {"input", "output", "hidden"} for i, n in self.nodes.items()
        ):
            raise ValueError("Invalid node")
        if self.next_node_id <= max(self.nodes):
            raise ValueError("Node identifier sequence is invalid")
        self.topological_order()
        pairs = [(e.source, e.target) for e in self.connections]
        if len(set(pairs)) != len(pairs):
            raise ValueError("Duplicate neural connections")
        for edge in self.connections:
            if self.nodes[edge.source].kind == "output" or self.nodes[edge.target].kind == "input":
                raise ValueError("Invalid connection direction")
        values = [e.weight for e in self.connections] + [n.bias for n in self.nodes.values()]
        if not all(np.isfinite(v) and abs(v) <= config.parameter_bound for v in values):
            raise ValueError("Invalid neural parameter")

    def mutated(self, config: NeuralConfig, rng: np.random.Generator) -> "Genome":
        child = self.clone()
        if not config.mutations:
            return child
        bound = config.parameter_bound
        for edge in child.connections:
            if rng.random() < config.weight_mutation_probability:
                edge.weight = float(
                    np.clip(edge.weight + rng.normal(0, config.mutation_std), -bound, bound)
                )
        for node in child.nodes.values():
            if node.kind != "input" and rng.random() < config.bias_mutation_probability:
                node.bias = float(
                    np.clip(node.bias + rng.normal(0, config.mutation_std), -bound, bound)
                )
        if child.connections and rng.random() < config.remove_connection_probability:
            child.connections.pop(int(rng.integers(len(child.connections))))
        hidden = sorted(i for i, n in child.nodes.items() if n.kind == "hidden")
        if hidden and rng.random() < config.remove_node_probability:
            i = int(rng.choice(hidden))
            del child.nodes[i]
            child.connections = [e for e in child.connections if i not in (e.source, e.target)]
        if (
            child.connections
            and len(child.nodes) < config.max_nodes
            and len(child.connections) + 1 <= config.max_connections
            and rng.random() < config.add_node_probability
        ):
            edge = child.connections.pop(int(rng.integers(len(child.connections))))
            i = child.next_node_id
            child.next_node_id += 1
            child.nodes[i] = Node(i, "hidden")
            child.connections.extend(
                [
                    Connection(edge.source, i, min(1.0, bound)),
                    Connection(i, edge.target, edge.weight),
                ]
            )
        if (
            len(child.connections) < config.max_connections
            and rng.random() < config.add_connection_probability
        ):
            order = child.topological_order()
            pairs = {(e.source, e.target) for e in child.connections}
            candidates = [
                (a, b)
                for j, a in enumerate(order)
                for b in order[j + 1 :]
                if child.nodes[a].kind != "output"
                and child.nodes[b].kind != "input"
                and (a, b) not in pairs
            ]
            if candidates:
                a, b = candidates[int(rng.integers(len(candidates)))]
                child.connections.append(
                    Connection(
                        a, b, float(np.clip(rng.normal(0, config.mutation_std), -bound, bound))
                    )
                )
        child.validate(config)
        return child

    def signature(self) -> str:
        data = (
            [(i, n.kind, n.bias) for i, n in sorted(self.nodes.items())],
            sorted((e.source, e.target, e.weight) for e in self.connections),
        )
        return hashlib.sha256(json.dumps(data, separators=(",", ":")).encode()).hexdigest()

    def distance(self, other: "Genome", bound: float) -> float:
        """Mean of node/edge Jaccard differences and normalized shared parameter distance."""
        nodes_a, nodes_b = set(self.nodes), set(other.nodes)
        a = {(e.source, e.target): e.weight for e in self.connections}
        b = {(e.source, e.target): e.weight for e in other.connections}
        edges_a, edges_b = set(a), set(b)
        node_difference = len(nodes_a ^ nodes_b) / max(1, len(nodes_a | nodes_b))
        edge_difference = len(edges_a ^ edges_b) / max(1, len(edges_a | edges_b))
        differences = [abs(a[k] - b[k]) / (2 * bound) for k in sorted(edges_a & edges_b)]
        differences += [
            abs(self.nodes[i].bias - other.nodes[i].bias) / (2 * bound)
            for i in sorted(nodes_a & nodes_b)
        ]
        parameter_difference = sum(differences) / max(1, len(differences))
        return (node_difference + edge_difference + parameter_difference) / 3
