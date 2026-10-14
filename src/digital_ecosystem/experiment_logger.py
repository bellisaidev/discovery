"""One-way scientific observations in SQLite and CSV. Never feeds the controller."""

import csv
import hashlib
import importlib.metadata
import json
import platform
import sqlite3
import uuid
import zlib
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import numpy as np

from . import __version__
from .state import canonical_json
from .storage import ExperimentLock, migrate

SAMPLE_COLUMNS = (
    "experiment_id",
    "tick",
    "simulated_time",
    "population",
    "births",
    "deaths",
    "mean_energy",
    "mean_neurons",
    "mean_connections",
    "mean_generation",
    "max_generation",
    "lineages",
    "distinct_genomes",
    "genetic_diversity",
    "diversity_pairs",
    "resource_energy",
    "contacts",
    "population_limit_hits",
    "signal0_emissions",
    "signal1_emissions",
    "signal0_amount",
    "signal1_amount",
    "initial_energy",
    "regenerated_energy",
    "dissipated_energy",
    "harvested_energy",
    "offspring_energy",
    "metabolic_dissipation",
    "action_dissipation",
    "reproductive_dissipation",
    "death_dissipation",
    "total_energy",
    "balance_error",
    "generation_distribution",
    "death_causes",
)
INDIVIDUAL_COLUMNS = (
    "experiment_id",
    "id",
    "parent_id",
    "lineage_id",
    "generation",
    "born_tick",
    "death_tick",
    "death_cause",
    "lifespan",
    "observed_age",
    "acquired_energy",
    "offspring",
    "descendants",
    "neurons",
    "connections",
    "genome_signature",
)


def observe_statistics(simulation) -> dict:
    organisms = list(simulation.world.organisms.values())
    count = len(organisms)

    def mean(values):
        return float(np.mean(values)) if count else 0.0

    # Deterministic pair reservoir, independent of every simulation RNG.
    # Hashes of IDs spread the sample across all genealogical ages.
    import heapq

    def pair_key(pair):
        a, b = pair
        return (((a.id * 0x9E3779B1) ^ (b.id * 0x85EBCA77)) & 0xFFFFFFFF, a.id, b.id)

    pairs = heapq.nsmallest(
        simulation.config.logging.diversity_pairs,
        ((a, b) for j, a in enumerate(organisms) for b in organisms[j + 1 :]),
        key=pair_key,
    )
    diversity = sum(
        a.genome.distance(b.genome, simulation.config.neural.parameter_bound) for a, b in pairs
    ) / max(1, len(pairs))
    generations = {}
    for o in organisms:
        generations[o.generation] = generations.get(o.generation, 0) + 1
    causes = {}
    for record in simulation.records.values():
        if record["death_cause"]:
            cause = record["death_cause"]
            causes[cause] = causes.get(cause, 0) + 1
    ledger = simulation.world.ledger
    emissions = simulation.signals.detectable_emissions if simulation.signals else [0, 0]
    amounts = simulation.signals.emitted if simulation.signals else [0.0, 0.0]
    return {
        "tick": simulation.tick,
        "simulated_time": simulation.tick * simulation.config.world.dt,
        "population": count,
        "births": simulation.births,
        "deaths": simulation.deaths,
        "mean_energy": mean([o.energy for o in organisms]),
        "mean_neurons": mean([len(o.genome.nodes) for o in organisms]),
        "mean_connections": mean([len(o.genome.connections) for o in organisms]),
        "mean_generation": mean([o.generation for o in organisms]),
        "max_generation": max((o.generation for o in organisms), default=0),
        "lineages": len({o.lineage_id for o in organisms}),
        "distinct_genomes": len({o.genome.signature() for o in organisms}),
        "genetic_diversity": diversity,
        "diversity_pairs": len(pairs),
        "resource_energy": float(simulation.world.resource_energy.sum()),
        "contacts": simulation.contacts,
        "population_limit_hits": simulation.population_limit_hits,
        "signal0_emissions": int(emissions[0]),
        "signal1_emissions": int(emissions[1]),
        "signal0_amount": float(amounts[0]),
        "signal1_amount": float(amounts[1]),
        "initial_energy": ledger.initial,
        "regenerated_energy": ledger.regenerated,
        "dissipated_energy": ledger.dissipated,
        "harvested_energy": ledger.harvested,
        "offspring_energy": ledger.inherited,
        "metabolic_dissipation": ledger.metabolic_dissipation,
        "action_dissipation": ledger.action_dissipation,
        "reproductive_dissipation": ledger.reproductive_dissipation,
        "death_dissipation": ledger.death_dissipation,
        "total_energy": simulation.world.total_energy(),
        "balance_error": simulation.world.energy_balance_error(),
        "generation_distribution": json.dumps(generations, sort_keys=True),
        "death_causes": json.dumps(causes, sort_keys=True),
    }


class ExperimentLogger:
    def __init__(self, simulation, output: str | Path = "experiments"):
        self.simulation = simulation
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.database = self.output / "lab.sqlite3"
        self.connection = sqlite3.connect(self.database)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.experiment_id = str(uuid.uuid4())
        self.closed = False
        self.last_sample = -1
        self.samples_since_commit = 0
        self._schema()
        migrate(self.connection, self.database)
        self.lock = ExperimentLock(self.output, self.experiment_id)
        self.archived_id = 0
        self.last_resource_positions = None
        software = {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "numpy": np.__version__,
            "pygame-ce": importlib.metadata.version("pygame-ce"),
        }
        source_hash = hashlib.sha256()
        for resource in sorted(files("digital_ecosystem").iterdir(), key=lambda r: r.name):
            if resource.name.endswith(".py"):
                source_hash.update(resource.name.encode())
                source_hash.update(resource.read_bytes())
        software["source_sha256"] = source_hash.hexdigest()
        self.connection.execute(
            "INSERT INTO experiments VALUES (?, ?, ?, ?, NULL, ?, ?, ?, NULL)",
            (
                self.experiment_id,
                simulation.seed,
                __version__,
                datetime.now(UTC).isoformat(),
                "running",
                json.dumps(simulation.config.to_dict(), sort_keys=True),
                json.dumps(software, sort_keys=True),
            ),
        )
        self.observe(force=True)
        self.connection.commit()

    def _schema(self):
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS experiments (
                id TEXT PRIMARY KEY, seed INTEGER, simulator_version TEXT, started_at TEXT,
                ended_at TEXT, status TEXT, config_json TEXT, software_json TEXT, summary_json TEXT
            );
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id TEXT REFERENCES experiments(id), tick INTEGER,
                kind TEXT, organism_id INTEGER, details_json TEXT
            );
            CREATE INDEX IF NOT EXISTS events_experiment ON events(experiment_id, tick);
            CREATE TABLE IF NOT EXISTS resources (
                experiment_id TEXT REFERENCES experiments(id), tick INTEGER, resource_id INTEGER,
                x REAL, y REAL, energy REAL, PRIMARY KEY(experiment_id, tick, resource_id)
            );
        """)
        text = {"experiment_id", "generation_distribution", "death_causes"}
        integer = {
            "tick",
            "population",
            "births",
            "deaths",
            "max_generation",
            "lineages",
            "distinct_genomes",
            "diversity_pairs",
            "contacts",
            "population_limit_hits",
            "signal0_emissions",
            "signal1_emissions",
        }
        columns = ", ".join(
            f"{c} {'TEXT' if c in text else 'INTEGER' if c in integer else 'REAL'}"
            for c in SAMPLE_COLUMNS
        )
        self.connection.execute(
            f"CREATE TABLE IF NOT EXISTS samples ({columns}, "
            "PRIMARY KEY(experiment_id, tick), "
            "FOREIGN KEY(experiment_id) REFERENCES experiments(id))"
        )
        text = {"experiment_id", "death_cause", "genome_signature"}
        real = {"lifespan", "observed_age", "acquired_energy"}
        columns = ", ".join(
            f"{c} {'TEXT' if c in text else 'REAL' if c in real else 'INTEGER'}"
            for c in INDIVIDUAL_COLUMNS
        )
        self.connection.execute(
            f"CREATE TABLE IF NOT EXISTS individuals ({columns}, "
            "PRIMARY KEY(experiment_id, id), "
            "FOREIGN KEY(experiment_id) REFERENCES experiments(id))"
        )

    def _write(self, statement, parameters=(), *, many=False):
        # Retain only the uncommitted observation batch, so a SQLite rollback
        # (including SQLITE_FULL) cannot silently discard drained engine queues.
        if not hasattr(self, "_pending_writes"):
            self._pending_writes = []
        self._pending_writes.append((statement, parameters, many))
        try:
            method = self.connection.executemany if many else self.connection.execute
            return method(statement, parameters)
        except sqlite3.Error as error:
            self.connection.rollback()
            self._retry_writes = True
            raise RuntimeError(f"SQLite observation write failed: {error}") from error

    def _recover_writes(self):
        if not getattr(self, "_retry_writes", False):
            return
        try:
            for statement, parameters, many in self._pending_writes:
                method = self.connection.executemany if many else self.connection.execute
                method(statement, parameters)
        except sqlite3.Error as error:
            self.connection.rollback()
            raise RuntimeError(f"SQLite observation retry failed: {error}") from error
        self._retry_writes = False
        self.archived_id = self.connection.execute(
            "SELECT coalesce(max(organism_id),0) FROM birth_genomes WHERE experiment_id=?",
            (self.experiment_id,),
        ).fetchone()[0]
        self.last_sample = self.connection.execute(
            "SELECT coalesce(max(tick),-1) FROM samples WHERE experiment_id=?",
            (self.experiment_id,),
        ).fetchone()[0]
        rows = self.connection.execute(
            "SELECT x,y FROM resources WHERE experiment_id=? AND tick=? ORDER BY resource_id",
            (self.experiment_id, self.last_sample),
        ).fetchall()
        self.last_resource_positions = np.asarray(rows, dtype=float).reshape((-1, 2))
        return True

    def observe(self, simulation=None, force=False):
        if self.closed:
            raise RuntimeError("Logger already closed")
        if simulation is not None and simulation is not self.simulation:
            raise ValueError("Logger belongs to a different experiment")
        recovered = self._recover_writes()
        simulation = self.simulation
        if simulation.pending_genomes:
            for content_id, genome in simulation.pending_genomes.items():
                self._write(
                    "INSERT OR IGNORE INTO genomes VALUES (?,?)",
                    (content_id, zlib.compress(canonical_json(genome), 1)),
                )
            for identifier, record in simulation.records.items():
                if identifier > self.archived_id:
                    self._write(
                        "INSERT OR IGNORE INTO birth_genomes VALUES (?,?,?)",
                        (self.experiment_id, identifier, record["genome_id"]),
                    )
            self.archived_id = max(simulation.records, default=0)
            simulation.pending_genomes.clear()
        self.append_events(simulation.events)
        simulation.events.clear()  # Observation queue only; never read by physical rules.
        if not force and simulation.tick % simulation.config.logging.sample_interval:
            return
        if simulation.tick == self.last_sample and not recovered:
            return
        positions = simulation.world.resource_positions
        changed = (
            np.ones(len(positions), dtype=bool)
            if self.last_resource_positions is None
            else np.any(positions != self.last_resource_positions, axis=1)
        )
        self._write(
            "INSERT OR IGNORE INTO resource_geometry_history VALUES (?,?,?,?,?)",
            [
                (
                    self.experiment_id,
                    simulation.tick,
                    int(i),
                    float(positions[i, 0]),
                    float(positions[i, 1]),
                )
                for i in np.flatnonzero(changed)
            ],
            many=True,
        )
        self.last_resource_positions = positions.copy()
        stats = observe_statistics(simulation)
        stats["experiment_id"] = self.experiment_id
        placeholders = ",".join("?" for _ in SAMPLE_COLUMNS)
        self._write(
            f"INSERT OR REPLACE INTO samples VALUES ({placeholders})",
            [stats[c] for c in SAMPLE_COLUMNS],
        )
        self._write(
            "INSERT OR REPLACE INTO resources VALUES (?, ?, ?, ?, ?, ?)",
            [
                (self.experiment_id, simulation.tick, i, float(p[0]), float(p[1]), float(energy))
                for i, (p, energy) in enumerate(
                    zip(
                        simulation.world.resource_positions,
                        simulation.world.resource_energy,
                        strict=True,
                    )
                )
            ],
            many=True,
        )
        values = []
        for identifier, record in sorted(simulation.records.items()):
            row = dict(record, experiment_id=self.experiment_id)
            living = simulation.world.organisms.get(identifier)
            row["observed_age"] = living.age if living else row["lifespan"]
            if living:
                row["acquired_energy"] = living.acquired_energy
                row["offspring"] = living.offspring
            values.append([row[c] for c in INDIVIDUAL_COLUMNS])
        placeholders = ",".join("?" for _ in INDIVIDUAL_COLUMNS)
        self._write(
            f"INSERT OR REPLACE INTO individuals VALUES ({placeholders})", values, many=True
        )
        self.last_sample = simulation.tick
        self.samples_since_commit += 1
        if force or self.samples_since_commit >= simulation.config.logging.batch_samples:
            self.commit_boundary()
            self.samples_since_commit = 0

    def append_events(self, events):
        for event in events:
            payload = json.dumps(event, sort_keys=True)
            existing = self.connection.execute(
                "SELECT details_json FROM events WHERE experiment_id=? AND event_seq=?",
                (self.experiment_id, event["sequence"]),
            ).fetchone()
            if existing:
                if existing[0] != payload:
                    raise ValueError("Conflicting event sequence payload")
                continue
            self._write(
                "INSERT INTO events (experiment_id,tick,kind,organism_id,details_json,event_seq) "
                "VALUES (?,?,?,?,?,?)",
                (
                    self.experiment_id,
                    event["tick"],
                    event["kind"],
                    event.get("organism_id"),
                    payload,
                    event["sequence"],
                ),
            )

    def commit_boundary(self, engine_hash=None):
        engine_hash = engine_hash or self.simulation.state_fingerprint()
        self._write(
            "INSERT OR REPLACE INTO experiment_heads VALUES (?,?,?,?)",
            (
                self.experiment_id,
                self.simulation.tick,
                self.simulation.event_sequence,
                engine_hash,
            ),
        )
        try:
            self.connection.commit()
        except sqlite3.Error as error:
            self.connection.rollback()
            self._retry_writes = True
            raise RuntimeError(f"SQLite observation commit failed: {error}") from error
        self._pending_writes.clear()
        self.committed_hash = engine_hash

    def flush(self):
        if not self.simulation.at_tick_boundary:
            raise ValueError("Cannot commit a partial simulation tick")
        self.observe(force=True)
        engine_hash = self.simulation.state_fingerprint()
        if self.connection.in_transaction or getattr(self, "committed_hash", None) != engine_hash:
            self.commit_boundary(engine_hash)
        return engine_hash

    def export_csv(self) -> Path:
        if not self.closed:
            self.flush()
        destination = self.output / self.experiment_id
        destination.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database) if self.closed else self.connection
        try:
            for table in ("experiments", "samples", "resources", "events", "individuals"):
                column = "id" if table == "experiments" else "experiment_id"
                order = (
                    "tick, resource_id"
                    if table == "resources"
                    else (
                        "tick" if table == "samples" else "event_id" if table == "events" else "id"
                    )
                )
                cursor = connection.execute(
                    f"SELECT * FROM {table} WHERE {column} = ? ORDER BY {order}",
                    (self.experiment_id,),
                )
                path = destination / f"{table}.csv"
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow([c[0] for c in cursor.description])
                    writer.writerows(cursor)
        finally:
            if self.closed:
                connection.close()
        return destination

    def close(self, status="completed") -> dict:
        if self.closed:
            return self.summary
        try:
            if not self.simulation.at_tick_boundary:
                self.connection.rollback()
                self.summary = {}
                self.connection.execute(
                    "UPDATE experiments SET ended_at=?, status='failed' WHERE id=?",
                    (datetime.now(UTC).isoformat(), self.experiment_id),
                )
                self.connection.commit()
                return self.summary
            self.observe(force=True)
            self.summary = observe_statistics(self.simulation)
            self.connection.execute(
                "UPDATE experiments SET ended_at=?, status=?, summary_json=? WHERE id=?",
                (
                    datetime.now(UTC).isoformat(),
                    status,
                    json.dumps(self.summary, sort_keys=True),
                    self.experiment_id,
                ),
            )
            self.connection.commit()
            return self.summary
        finally:
            self.connection.close()
            self.closed = True
            self.lock.close()
