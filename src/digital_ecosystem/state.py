"""Lossless data-only state transport, with no random initialization during restore."""

import copy
import hashlib
import json
from collections import deque
from dataclasses import asdict, fields

import numpy as np

from .brain import Brain
from .configuration import Configuration
from .genome import Genome
from .organism import Organism
from .physics import Physics
from .reproduction import Reproduction
from .sensors import Sensors
from .signals import SignalField
from .world import EnergyLedger, SpatialIndex, World

STATE_VERSION = 1


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(state) -> str:
    digest = hashlib.sha256()

    def visit(value):
        if isinstance(value, np.ndarray):
            digest.update(b"array")
            digest.update(
                canonical_json(
                    [value.dtype.descr if value.dtype.fields else value.dtype.str, value.shape]
                )
            )
            digest.update(value.tobytes(order="C"))
        elif isinstance(value, dict):
            digest.update(b"dict")
            for key in sorted(value):
                digest.update(canonical_json(key))
                visit(value[key])
        elif isinstance(value, (list, tuple)):
            digest.update(canonical_json(["list", len(value)]))
            for item in value:
                visit(item)
        else:
            digest.update(canonical_json(value))

    visit(state)
    return digest.hexdigest()


def capture(simulation) -> dict:
    if not simulation.at_tick_boundary:
        raise ValueError("State is not at a completed tick boundary")
    world = simulation.world
    organisms = []
    for organism in world.organisms.values():
        body = {
            f.name: copy.deepcopy(getattr(organism, f.name))
            for f in fields(organism)
            if f.name not in {"brain", "genome"}
        }
        body["genome"] = organism.genome.to_data()
        body["brain"] = {
            name: getattr(organism.brain, name).copy()
            for name in ("activities", "acquired", "last_outputs")
        }
        organisms.append(body)
    signals = None
    if simulation.signals is not None:
        field = simulation.signals
        signals = {
            name: getattr(field, name).copy()
            for name in (
                "field",
                "emitted",
                "detectable_emissions",
                "px",
                "py",
                "kx",
                "ky",
                "decays",
            )
        }
        signals.update(
            tick=field.tick,
            decay=field.decay,
            history=copy.deepcopy(list(field.history)),
            own_history=[(int(i), trace.copy()) for i, trace in field.own_history.items()],
        )
    return {
        "version": STATE_VERSION,
        "config": simulation.config.to_dict(),
        "seed": simulation.seed,
        "tick": simulation.tick,
        "time": simulation.tick * simulation.config.world.dt,
        "organisms": organisms,
        "resource_positions": world.resource_positions.copy(),
        "resource_energy": world.resource_energy.copy(),
        "resource_active": world.resource_active.copy(),
        "ledger": asdict(world.ledger),
        "signals": signals,
        "records": copy.deepcopy(list(simulation.records.items())),
        "events": copy.deepcopy(simulation.events),
        "event_sequence": simulation.event_sequence,
        "pending_genomes": copy.deepcopy(simulation.pending_genomes),
        "counters": {
            name: getattr(simulation, name)
            for name in ("births", "deaths", "contacts", "population_limit_hits")
        },
        "physics_contacts": simulation.physics.contacts,
        "reproduction": {
            "next_id": simulation.reproduction.next_id,
            "rng_type": type(simulation.reproduction.placement_rng.bit_generator).__name__,
            "rng": copy.deepcopy(simulation.reproduction.placement_rng.bit_generator.state),
            "mutation_seed": simulation.reproduction.mutation_seed.state,
        },
        "relocation_rng": {
            "rng_type": type(world.relocation_rng.bit_generator).__name__,
            "rng": copy.deepcopy(world.relocation_rng.bit_generator.state),
        }
        if getattr(world, "relocation_rng", None) is not None
        else None,
    }


def _array(value, shape, dtype=np.float64):
    if not isinstance(value, np.ndarray) or value.shape != shape or value.dtype != np.dtype(dtype):
        raise ValueError("Invalid state array shape or dtype")
    if value.dtype.fields is None and not np.all(np.isfinite(value)):
        raise ValueError("Nonfinite state array")
    return value.copy()


def restore(state: dict):
    from .simulation import Simulation

    if state["version"] != STATE_VERSION:
        raise ValueError("Unsupported numerical state version")
    config = Configuration.from_dict(state["config"])
    if type(state["tick"]) is not int or state["tick"] < 0:
        raise ValueError("Invalid tick")
    if state["time"] != state["tick"] * config.world.dt or not 0 <= state["seed"] < 2**63:
        raise ValueError("Invalid state time or seed")
    simulation = Simulation.__new__(Simulation)
    simulation.config, simulation.seed, simulation.tick = config, state["seed"], state["tick"]
    world = World.__new__(World)
    world.config = config
    count = config.world.resource_count
    world.resource_positions = _array(state["resource_positions"], (count, 2))
    world.resource_energy = _array(state["resource_energy"], (count,))
    if "resource_active" in state:
        world.resource_active = _array(state["resource_active"], (count,), dtype=bool)
    else:
        world.resource_active = np.ones(count, dtype=bool)
    if np.any(world.resource_energy < 0) or np.any(
        world.resource_energy > config.world.resource_capacity
    ):
        raise ValueError("Invalid resource energy")
    world.ledger = EnergyLedger(**state["ledger"])
    if any(not np.isfinite(v) or v < 0 for v in asdict(world.ledger).values()):
        raise ValueError("Invalid energy ledger")
    world.organisms = {}
    if config.world.max_population and len(state["organisms"]) > config.world.max_population:
        raise ValueError("Population exceeds configured capacity")
    for body in state["organisms"]:
        body = dict(body)
        genome = Genome.from_data(body.pop("genome"), config.neural)
        brain_state = body.pop("brain")
        brain = Brain(genome, config.neural)
        for name in ("activities", "acquired", "last_outputs"):
            current = getattr(brain, name)
            setattr(brain, name, _array(brain_state[name], current.shape))
        for name, shape in (
            ("position", (2,)),
            ("velocity", (2,)),
            ("sensors", (16,)),
            ("outputs", (6,)),
        ):
            body[name] = _array(body[name], shape)
        organism = Organism(**body, genome=genome, brain=brain)
        if (
            organism.id in world.organisms
            or organism.energy < 0
            or not np.isfinite(organism.energy)
        ):
            raise ValueError("Invalid organism")
        scalars = (
            organism.orientation,
            organism.age,
            organism.last_birth_age,
            organism.radius,
            organism.mass,
            organism.acquired_energy,
        )
        if not all(np.isfinite(value) for value in scalars):
            raise ValueError("Nonfinite body state")
        if (
            type(organism.id) is not int
            or organism.id <= 0
            or organism.radius <= 0
            or organism.mass <= 0
            or organism.age < 0
            or organism.acquired_energy < 0
            or organism.energy > config.body.energy_capacity
            or organism.born_tick > simulation.tick
            or np.any(np.abs(brain.acquired) > config.neural.plastic_bound)
        ):
            raise ValueError("Invalid physical or learned state")
        bounds = np.array([config.world.width, config.world.height])
        if np.any(organism.position < organism.radius - 1e-8) or np.any(
            organism.position > bounds - organism.radius + 1e-8
        ):
            raise ValueError("Body is outside the solid boundaries")
        world.organisms[organism.id] = organism
    if config.world.max_population and len(world.organisms) > config.world.max_population:
        raise ValueError("Population exceeds configured capacity")
    cell_size = max(2 * config.body.radius, config.sensors.range)
    world.body_index, world.resource_index = SpatialIndex(cell_size), SpatialIndex(cell_size)
    world.rebuild_resource_index()
    world.rebuild_body_index()
    simulation.world, simulation.physics = world, Physics(world)
    simulation.physics.contacts = state["physics_contacts"]
    simulation.sensors = Sensors(world)
    simulation.signals = None
    if state["signals"] is not None:
        if not config.signals.enabled:
            raise ValueError("Signals present in disabled configuration")
        data = state["signals"]
        field = SignalField.__new__(SignalField)
        field.config = config
        field.trace_dtype = np.dtype(
            [("tick", "i8"), ("x", "i4"), ("y", "i4"), ("amplitude", "f8", (2,))]
        )
        s = config.signals
        shapes = {
            "field": (2, s.rows, s.columns),
            "emitted": (2,),
            "detectable_emissions": (2,),
            "px": (s.columns, s.columns),
            "py": (s.rows, s.rows),
            "kx": (s.lifetime_ticks + 1, s.columns, s.columns),
            "ky": (s.lifetime_ticks + 1, s.rows, s.rows),
            "decays": (s.lifetime_ticks + 1,),
        }
        for name, shape in shapes.items():
            dtype = np.dtype(int) if name == "detectable_emissions" else np.float64
            setattr(field, name, _array(data[name], shape, dtype))
        field.tick, field.decay = data["tick"], data["decay"]
        field.history = deque(copy.deepcopy(data["history"]))
        field.own_history = {
            i: _array(trace, (s.lifetime_ticks,), field.trace_dtype)
            for i, trace in data["own_history"]
        }
        if field.tick != simulation.tick or len(field.history) > s.lifetime_ticks:
            raise ValueError("Invalid signal history")
        expected_ticks = list(
            range(max(1, simulation.tick - s.lifetime_ticks + 1), simulation.tick + 1)
        )
        if [item[0] for item in field.history] != expected_ticks:
            raise ValueError("Incomplete signal expiration history")
        for tick, identifiers, xs, ys, amplitudes in field.history:
            count = len(identifiers)
            _array(identifiers, (count,), np.int64)
            _array(xs, (count,), np.intp)
            _array(ys, (count,), np.intp)
            _array(amplitudes, (count, 2))
            if (
                len(set(identifiers)) != count
                or np.any(xs < 0)
                or np.any(xs >= s.columns)
                or np.any(ys < 0)
                or np.any(ys >= s.rows)
                or np.any(amplitudes < 0)
            ):
                raise ValueError("Invalid signal source history")
            for identifier, x, y, amplitude in zip(identifiers, xs, ys, amplitudes, strict=True):
                trace = field.own_history.get(int(identifier))
                if trace is None:
                    raise ValueError("Missing self-exclusion history")
                entry = trace[tick % s.lifetime_ticks]
                if (
                    entry["tick"] != tick
                    or entry["x"] != x
                    or entry["y"] != y
                    or not np.array_equal(entry["amplitude"], amplitude)
                ):
                    raise ValueError("Self-exclusion history is inconsistent")
        if np.any(field.field < 0) or not np.isfinite(field.decay):
            raise ValueError("Invalid diffusive field")
        simulation.signals = field
    elif config.signals.enabled:
        raise ValueError("Missing signal fields")
    reproduction = state["reproduction"]
    if reproduction["rng_type"] != "PCG64":
        raise ValueError("Unsupported generator")
    bit_generator = np.random.PCG64(0)
    bit_generator.state = reproduction["rng"]
    simulation.reproduction = Reproduction(
        world,
        np.random.Generator(bit_generator),
        np.random.SeedSequence(**reproduction["mutation_seed"]),
    )
    simulation.reproduction.next_id = reproduction["next_id"]
    if state.get("relocation_rng") is not None:
        reloc = state["relocation_rng"]
        if reloc["rng_type"] != "PCG64":
            raise ValueError("Unsupported generator")
        reloc_bg = np.random.PCG64(0)
        reloc_bg.state = reloc["rng"]
        world.relocation_rng = np.random.Generator(reloc_bg)
    else:
        relocation_seed = np.random.SeedSequence(state["seed"], spawn_key=(5,))
        world.relocation_rng = np.random.default_rng(relocation_seed)
    world_seed = np.random.SeedSequence(state["seed"]).spawn(5)[0]
    world.rng = np.random.default_rng(world_seed)
    simulation.records = {i: record for i, record in copy.deepcopy(state["records"])}
    for name, value in state["counters"].items():
        setattr(simulation, name, value)
    simulation.events = copy.deepcopy(state["events"])
    simulation.event_sequence = state["event_sequence"]
    simulation.pending_genomes = copy.deepcopy(state["pending_genomes"])
    simulation.at_tick_boundary = True
    if world.organisms.keys() - simulation.records.keys():
        raise ValueError("Missing genealogy")
    for identifier, record in simulation.records.items():
        if record["id"] != identifier or identifier <= 0:
            raise ValueError("Invalid genealogy identifier")
        parent_id = record["parent_id"]
        if parent_id is not None:
            if parent_id not in simulation.records or parent_id >= identifier:
                raise ValueError("Invalid or cyclic genealogy")
            parent = simulation.records[parent_id]
            if (
                record["generation"] != parent["generation"] + 1
                or record["lineage_id"] != parent["lineage_id"]
            ):
                raise ValueError("Invalid generation or lineage")
        elif record["lineage_id"] != identifier or record["generation"] != 0:
            raise ValueError("Invalid founder lineage")
    if simulation.event_sequence < max((e["sequence"] for e in simulation.events), default=0):
        raise ValueError("Invalid event delivery cursor")
    if simulation.reproduction.next_id <= max(simulation.records, default=0):
        raise ValueError("Invalid organism ID sequence")
    return simulation
