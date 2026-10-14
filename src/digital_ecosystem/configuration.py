"""Validated physical and experimental parameters; no behavioural objectives."""

import math
import tomllib
from dataclasses import asdict, dataclass, field, fields
from importlib.resources import files
from pathlib import Path


@dataclass
class WorldConfig:
    width: float = 1000.0
    height: float = 700.0
    dt: float = 1 / 30
    initial_population: int = 10
    max_population: int = 256  # 0 = unlimited computational capacity
    resource_count: int = 140
    resource_radius: float = 7.0
    resource_capacity: float = 40.0
    resource_regeneration: float = 0.08


@dataclass
class BodyConfig:
    radius: float = 6.0
    mass: float = 1.0
    initial_energy: float = 100.0
    energy_capacity: float = 220.0
    metabolism: float = 0.6
    acceleration: float = 45.0
    max_speed: float = 45.0
    drag: float = 1.0
    turn_rate: float = 3.0
    movement_cost: float = 0.003  # energy / squared control acceleration / second
    rotation_cost: float = 0.08
    harvesting_rate: float = 16.0
    harvesting_cost: float = 0.08
    max_age: float = 0.0  # 0 = no age mortality
    collision_iterations: int = 12


@dataclass
class SensorConfig:
    range: float = 90.0
    sector_half_angle: float = 0.7


@dataclass
class NeuralConfig:
    hidden_neurons: int = 8
    initial_weight_std: float = 0.35
    initial_variation: float = 0.025
    max_nodes: int = 96
    max_connections: int = 1500
    parameter_bound: float = 4.0
    plasticity: bool = True
    learning_rate: float = 0.02
    plastic_decay: float = 0.1
    plastic_bound: float = 0.5
    mutations: bool = True
    weight_mutation_probability: float = 0.1
    bias_mutation_probability: float = 0.08
    mutation_std: float = 0.12
    add_connection_probability: float = 0.1
    remove_connection_probability: float = 0.05
    add_node_probability: float = 0.03
    remove_node_probability: float = 0.01


@dataclass
class ReproductionConfig:
    threshold: float = 0.65
    minimum_energy: float = 150.0
    offspring_energy: float = 55.0
    cost: float = 8.0
    reserve: float = 15.0
    cooldown: float = 8.0
    placement_attempts: int = 12


@dataclass
class SignalConfig:
    enabled: bool = True
    columns: int = 25
    rows: int = 18
    diffusion: float = 150.0
    decay: float = 1.0
    lifetime_ticks: int = 30
    emission_rate: float = 2.0
    emission_cost: float = 0.15
    sensor_scale: float = 1.0


@dataclass
class LoggingConfig:
    sample_interval: int = 30
    batch_samples: int = 20
    diversity_pairs: int = 128


@dataclass
class Configuration:
    world: WorldConfig = field(default_factory=WorldConfig)
    body: BodyConfig = field(default_factory=BodyConfig)
    sensors: SensorConfig = field(default_factory=SensorConfig)
    neural: NeuralConfig = field(default_factory=NeuralConfig)
    reproduction: ReproductionConfig = field(default_factory=ReproductionConfig)
    signals: SignalConfig = field(default_factory=SignalConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Configuration":
        config = cls()
        if path is None:
            source_preset = Path(__file__).resolve().parents[2] / "configs" / "experimental.toml"
            path = (
                source_preset
                if source_preset.is_file()
                else files("digital_ecosystem").joinpath("presets", "experimental.toml")
            )
        if path is not None:
            with path.open("rb") if hasattr(path, "open") else Path(path).open("rb") as stream:
                data = tomllib.load(stream)
            sections = {f.name for f in fields(config)}
            if data.keys() - sections:
                unknown = sorted(data.keys() - sections)
                raise ValueError(f"Unknown configuration sections: {unknown}")
            for section, values in data.items():
                target = getattr(config, section)
                allowed = {f.name for f in fields(target)}
                if not isinstance(values, dict) or values.keys() - allowed:
                    raise ValueError(f"Invalid fields in [{section}]")
                for name, value in values.items():
                    setattr(target, name, value)
        config.validate()
        return config

    def validate(self) -> None:
        for section in fields(self):
            target = getattr(self, section.name)
            for param in fields(target):
                value = getattr(target, param.name)
                default = param.default
                label = f"{section.name}.{param.name}"
                if isinstance(default, bool):
                    if not isinstance(value, bool):
                        raise ValueError(f"{label} must be boolean")
                elif isinstance(default, int):
                    if type(value) is not int or value < 0:
                        raise ValueError(f"{label} must be a nonnegative integer")
                elif not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"{label} must be numeric")
                elif not math.isfinite(value) or value < 0:
                    raise ValueError(f"{label} must be finite and nonnegative")
        w, b, n, s, r = self.world, self.body, self.neural, self.signals, self.reproduction
        for label, value in {
            "world.dt": w.dt,
            "body.radius": b.radius,
            "body.mass": b.mass,
            "body.energy_capacity": b.energy_capacity,
            "body.collision_iterations": b.collision_iterations,
            "sensors.range": self.sensors.range,
            "world.resource_capacity": w.resource_capacity,
            "signals.columns": s.columns,
            "signals.rows": s.rows,
            "signals.lifetime_ticks": s.lifetime_ticks,
            "signals.sensor_scale": s.sensor_scale,
            "logging.sample_interval": self.logging.sample_interval,
            "logging.batch_samples": self.logging.batch_samples,
            "logging.diversity_pairs": self.logging.diversity_pairs,
            "reproduction.placement_attempts": r.placement_attempts,
            "neural.parameter_bound": n.parameter_bound,
        }.items():
            if value <= 0:
                raise ValueError(f"{label} must be positive")
        if w.width <= 4 * b.radius or w.height <= 4 * b.radius:
            raise ValueError("World is too small for the configured bodies")
        if w.dt * b.max_speed > b.radius:
            raise ValueError("Timestep permits body tunneling: reduce dt or maximum speed")
        if b.initial_energy > b.energy_capacity:
            raise ValueError("Initial energy exceeds body capacity")
        if w.max_population and w.initial_population > w.max_population:
            raise ValueError("Initial population exceeds computational capacity")
        if r.offspring_energy <= 0 or r.offspring_energy > b.energy_capacity:
            raise ValueError("Invalid offspring energy")
        if r.offspring_energy + r.cost + r.reserve > b.energy_capacity:
            raise ValueError("Reproduction energy requirements exceed capacity")
        if n.max_nodes < 22 + n.hidden_neurons:
            raise ValueError("Neural node limit is smaller than the initial architecture")
        initial_edges = 16 * n.hidden_neurons + 6 * n.hidden_neurons
        if not n.hidden_neurons:
            initial_edges = 16 * 6
        if n.max_connections < initial_edges:
            raise ValueError("Connection limit is smaller than the initial architecture")
        for name, value in asdict(n).items():
            if name.endswith("probability") and value > 1:
                raise ValueError(f"neural.{name} must be in [0, 1]")
        if not 0 <= r.threshold <= 1:
            raise ValueError("Reproduction threshold must be in [0, 1]")
        if not 0 < self.sensors.sector_half_angle <= math.pi:
            raise ValueError("Sensor half-angle must be in (0, pi]")

    def to_dict(self) -> dict:
        return asdict(self)
