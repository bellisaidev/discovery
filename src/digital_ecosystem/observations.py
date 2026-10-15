"""Detached observations. No inference, learning, physics or simulation RNG calls."""

import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from .observation_hash import engine_fingerprint
from .state import canonical_json


@dataclass(frozen=True)
class NeuralSnapshot:
    experiment_id: str
    organism_id: int
    tick: int
    genome_id: str
    genome: dict
    activities: tuple | None = None
    acquired: tuple | None = None
    sensors: tuple | None = None
    outputs: tuple | None = None
    phase: str = "genetic_only"
    engine_hash: str = ""
    event_sequence: int = 0

    def payload(self):
        return {
            "version": 1,
            "node_ids": sorted(
                self.genome["nodes"][i][0] for i in range(len(self.genome["nodes"]))
            ),
            "activities": self.activities,
            "acquired": self.acquired,
            "sensors": self.sensors,
            "outputs": self.outputs,
            "phase": self.phase,
        }

    def weights(self, bound):
        genetic = np.array([e[2] for e in self.genome["connections"]], dtype=float)
        if self.acquired is None:
            return genetic, None
        return genetic, np.clip(genetic + self.acquired, -bound, bound)


class SamplingPolicy(Protocol):
    """Future automatic policies run outside the numerical core, at tick boundaries.

    A policy returns organism IDs to capture; persistence uses the same writer as
    manual requests. No automatic policy is enabled or scheduled in M5/M6.
    """

    def requested_ids(self, tick: int, living_ids: tuple[int, ...]) -> tuple[int, ...]: ...


def capture_neural(
    simulation, identifier, experiment_id="current", *, provenance=False, _genetic=None
):
    if not simulation.at_tick_boundary:
        raise ValueError("Neural observations require a completed tick")
    organism = simulation.world.organisms.get(identifier)
    if organism is None:
        raise ValueError("Organism is not alive; consult recorded historical data")
    # Only the GUI passes its detached birth-genome cache. Persistent captures
    # always serialize afresh; numeric genomes are immutable during an individual's life.
    if _genetic is None or provenance:
        genome = organism.genome.to_data()
        genome_id = hashlib.sha256(canonical_json(genome)).hexdigest()
    else:
        genome_id, genome = _genetic
    return NeuralSnapshot(
        experiment_id,
        identifier,
        simulation.tick,
        genome_id,
        genome,
        tuple(float(x) for x in organism.brain.activities),
        tuple(float(x) for x in organism.brain.acquired),
        tuple(float(x) for x in organism.sensors),
        tuple(float(x) for x in organism.outputs),
        "not_evaluated" if organism.born_tick == simulation.tick else "post_learning",
        engine_fingerprint(simulation) if provenance else "",
        simulation.event_sequence,
    )


@dataclass(frozen=True)
class InterventionRecord:
    id: str
    experiment_id: str
    tick: int
    kind: str
    label: str
    payload_version: int
    payload: dict


class ObservationWriter:
    def __init__(self, logger):
        self.logger = logger

    def _ready(self):
        logger = self.logger
        if logger.closed or not logger.simulation.at_tick_boundary:
            raise ValueError("Observation writer requires an open session at a tick boundary")
        logger._recover_writes()
        if logger.simulation.events or logger.simulation.pending_genomes:
            raise ValueError("Record pending tick observations before capturing")

    def _persist(self, statement, values):
        writes = [
            (statement, values, False),
            (
                "INSERT INTO observation_revisions VALUES (?,1) ON CONFLICT(experiment_id) "
                "DO UPDATE SET revision=revision+1",
                (self.logger.experiment_id,),
                False,
            ),
        ]
        for index, (sql, parameters, _) in enumerate(writes):
            try:
                self.logger._write(sql, parameters)
            except RuntimeError:
                # The logger retains the failed write. Retain the remainder too,
                # so rollback/replay never loses the observation revision.
                self.logger._pending_writes.extend(writes[index + 1 :])
                raise

    def capture(self, identifier):
        self._ready()
        logger = self.logger
        snapshot = capture_neural(
            logger.simulation, identifier, logger.experiment_id, provenance=True
        )
        payload = canonical_json(snapshot.payload())
        checksum = hashlib.sha256(payload).hexdigest()
        existing = logger.connection.execute(
            "SELECT payload_hash,engine_hash FROM neural_snapshots "
            "WHERE experiment_id=? AND organism_id=? AND tick=?",
            (snapshot.experiment_id, identifier, snapshot.tick),
        ).fetchone()
        if existing and tuple(existing) != (checksum, snapshot.engine_hash):
            raise ValueError("Conflicting neural snapshot for the same trajectory and tick")
        if not existing:
            self._persist(
                "INSERT INTO neural_snapshots VALUES (?,?,?,?,?,?,?,?)",
                (
                    snapshot.experiment_id,
                    identifier,
                    snapshot.tick,
                    snapshot.genome_id,
                    snapshot.engine_hash,
                    snapshot.event_sequence,
                    checksum,
                    zlib.compress(payload, 1),
                ),
            )
        logger.commit_boundary(snapshot.engine_hash)
        return snapshot

    def append_intervention(self, record: InterventionRecord):
        """Future integration boundary; never applies or schedules an intervention."""
        self._ready()
        logger = self.logger
        if (
            record.experiment_id != logger.experiment_id
            or record.tick != logger.simulation.tick
            or record.payload_version < 1
            or not record.id
            or not record.kind
        ):
            raise ValueError("Intervention observation does not match the current boundary")
        values = (
            record.experiment_id,
            record.id,
            record.tick,
            record.kind,
            record.label,
            record.payload_version,
            canonical_json(record.payload).decode(),
        )
        existing = logger.connection.execute(
            "SELECT * FROM interventions WHERE experiment_id=? AND id=?", values[:2]
        ).fetchone()
        if existing and tuple(existing) != values:
            raise ValueError("Conflicting intervention observation")
        if not existing:
            self._persist("INSERT INTO interventions VALUES (?,?,?,?,?,?,?)", values)
        logger.commit_boundary()


def dictionaries(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor]


def decode_record(blob, checksum, label):
    try:
        payload = zlib.decompress(blob)
        if hashlib.sha256(payload).hexdigest() != checksum:
            raise ValueError(f"{label} checksum mismatch")
        return json.loads(payload)
    except (zlib.error, TypeError, UnicodeError) as error:
        raise ValueError(f"Invalid {label} payload") from error


class ExperimentReader:
    """Read-only API; a live reader borrows the writer connection without committing.

    Archive readers own a mode=ro connection. The borrowed connection's row factory,
    transaction, PRAGMAs and lifetime are never changed by the reader.
    """

    def __init__(self, database=None, *, connection=None, experiment_id=None):
        self.owned = connection is None
        self.database = Path(database) if database is not None else None
        self.connection = connection
        try:
            if self.owned:
                self.connection = sqlite3.connect(
                    self.database.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1
                )
                self.connection.execute("PRAGMA query_only=ON")
                self.connection.execute("PRAGMA trusted_schema=OFF")
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2, 3, 103, 104}:
                raise ValueError("Unsupported observational database schema")
            self.tables = {
                row[0]
                for row in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
                )
            }
            if not {"experiments", "samples", "individuals", "events"} <= self.tables:
                raise ValueError("Not a Digital Life Lab experiment database")
            self.experiment_id = experiment_id
            if experiment_id is not None and self.metadata(experiment_id) is None:
                raise ValueError("Experiment not found in this database")
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.owned and self.connection is not None:
            self.connection.close()
            self.connection = None

    def experiments(self, *, after="", limit=100):
        return dictionaries(
            self.connection.execute(
                "SELECT * FROM experiments WHERE id>? ORDER BY id LIMIT ?", (after, min(limit, 500))
            )
        )

    def metadata(self, identifier=None):
        rows = dictionaries(
            self.connection.execute(
                "SELECT * FROM experiments WHERE id=?", (identifier or self.experiment_id,)
            )
        )
        return rows[0] if rows else None

    def bounds(self):
        row = self.connection.execute(
            "SELECT min(tick),max(tick) FROM samples WHERE experiment_id=?", (self.experiment_id,)
        ).fetchone()
        return tuple(row)

    def samples(self, start=0, end=2**63 - 1, *, after=-1, limit=1000):
        return dictionaries(
            self.connection.execute(
                "SELECT * FROM samples WHERE experiment_id=? AND tick>? AND tick<=? "
                "ORDER BY tick LIMIT ?",
                (self.experiment_id, max(start - 1, after), end, min(limit, 2000)),
            )
        )

    def individual(self, identifier, tick=None):
        rows = dictionaries(
            self.connection.execute(
                "SELECT * FROM individuals WHERE experiment_id=? AND id=?",
                (self.experiment_id, identifier),
            )
        )
        if not rows or (tick is not None and rows[0]["born_tick"] > tick):
            return None
        row = rows[0]
        if tick is not None:
            dt = json.loads(self.metadata()["config_json"])["world"]["dt"]
            if row["death_tick"] is None or row["death_tick"] > tick:
                row.update(
                    death_tick=None,
                    death_cause=None,
                    lifespan=None,
                    observed_age=(tick - row["born_tick"]) * dt,
                )
            # Lifetime totals are not available at an earlier historical boundary.
            row.pop("acquired_energy", None)
            row.pop("offspring", None)
            row.pop("descendants", None)
        return row

    def individuals(self, *, after=0, limit=100, tick=2**63 - 1, parent=None, lineage=None):
        clause = ""
        values = [self.experiment_id, after, tick]
        if parent is not None:
            clause += " AND parent_id=?"
            values.append(parent)
        if lineage is not None:
            clause += " AND lineage_id=?"
            values.append(lineage)
        values.append(min(limit, 500))
        return dictionaries(
            self.connection.execute(
                "SELECT id,parent_id,lineage_id,generation,born_tick,death_tick FROM individuals "
                f"WHERE experiment_id=? AND id>? AND born_tick<=?{clause} ORDER BY id LIMIT ?",
                values,
            )
        )

    def ancestors(self, identifier, *, limit=100, tick=None):
        result, seen = [], {identifier}
        row = self.individual(identifier, tick)
        while row and row["parent_id"] is not None and len(result) < limit:
            identifier = row["parent_id"]
            if identifier in seen:
                raise ValueError("Cycle in archived genealogy")
            seen.add(identifier)
            row = self.individual(identifier, tick)
            if row:
                result.append(row)
        return result

    def genome(self, identifier):
        if not {"birth_genomes", "genomes"} <= self.tables:
            return None
        row = self.connection.execute(
            "SELECT g.content_id,g.payload FROM genomes g JOIN birth_genomes b "
            "ON b.genome_id=g.content_id WHERE b.experiment_id=? AND b.organism_id=?",
            (self.experiment_id, identifier),
        ).fetchone()
        if row is None:
            return None
        genome = decode_record(row[1], row[0], "archived genome")
        return NeuralSnapshot(self.experiment_id, identifier, -1, row[0], genome)

    def snapshots(self, identifier, *, after=-1, end=2**63 - 1, limit=100):
        if "neural_snapshots" not in self.tables:
            return []
        return dictionaries(
            self.connection.execute(
                "SELECT organism_id,tick,genome_id,engine_hash,event_sequence "
                "FROM neural_snapshots WHERE experiment_id=? AND organism_id=? "
                "AND tick>? AND tick<=? ORDER BY tick LIMIT ?",
                (self.experiment_id, identifier, after, end, min(limit, 500)),
            )
        )

    def snapshot(self, identifier, tick):
        if "neural_snapshots" not in self.tables:
            return None
        row = self.connection.execute(
            "SELECT genome_id,engine_hash,event_sequence,payload_hash,payload "
            "FROM neural_snapshots "
            "WHERE experiment_id=? AND organism_id=? AND tick=?",
            (self.experiment_id, identifier, tick),
        ).fetchone()
        if row is None:
            return None
        data = decode_record(row[4], row[3], "neural snapshot")
        genome = self.genome(identifier)
        if genome is None or genome.genome_id != row[0] or data["version"] != 1:
            raise ValueError("Neural snapshot genome or version mismatch")
        node_ids = sorted(n[0] for n in genome.genome["nodes"])
        if data["node_ids"] != node_ids:
            raise ValueError("Neural snapshot node mapping mismatch")
        for key, size in (
            ("activities", len(node_ids)),
            ("acquired", len(genome.genome["connections"])),
            ("sensors", 16),
            ("outputs", 6),
        ):
            if len(data[key]) != size or not np.all(np.isfinite(data[key])):
                raise ValueError("Invalid neural snapshot array")
        return NeuralSnapshot(
            self.experiment_id,
            identifier,
            tick,
            row[0],
            genome.genome,
            *(tuple(data[k]) for k in ("activities", "acquired", "sensors", "outputs")),
            data["phase"],
            row[1],
            row[2],
        )

    def interventions(self, start=0, end=2**63 - 1, *, after_tick=-1, after_id="", limit=500):
        if "interventions" not in self.tables:
            return []
        comparison = ">"
        if after_tick < start:
            after_tick, after_id, comparison = start, "", ">="
        return dictionaries(
            self.connection.execute(
                f"SELECT * FROM interventions WHERE experiment_id=? AND (tick,id){comparison}(?,?) "
                "AND tick<=? ORDER BY tick,id LIMIT ?",
                (self.experiment_id, after_tick, after_id, end, min(limit, 500)),
            )
        )


def genetic_difference(individual, ancestor):
    a = {n[0]: n for n in individual.genome["nodes"]}
    b = {n[0]: n for n in ancestor.genome["nodes"]}
    ae = {(e[0], e[1]): e[2] for e in individual.genome["connections"]}
    be = {(e[0], e[1]): e[2] for e in ancestor.genome["connections"]}
    return {
        "nodes_added": sorted(a.keys() - b.keys()),
        "nodes_removed": sorted(b.keys() - a.keys()),
        "bias_changed": {k: a[k][2] - b[k][2] for k in a.keys() & b.keys() if a[k][2] != b[k][2]},
        "edges_added": sorted(ae.keys() - be.keys()),
        "edges_removed": sorted(be.keys() - ae.keys()),
        "weights_changed": {k: ae[k] - be[k] for k in ae.keys() & be.keys() if ae[k] != be[k]},
    }
