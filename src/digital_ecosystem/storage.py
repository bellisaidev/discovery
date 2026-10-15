"""Versioned observational storage and experiment-scoped SQLite transport."""

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 3
SNAPSHOT_VERSION = 104
TABLES = (
    "samples",
    "resources",
    "events",
    "individuals",
    "birth_genomes",
    "experiment_heads",
    "experiment_origins",
    "resource_geometry_history",
)
OBSERVATION_TABLES = ("neural_snapshots", "interventions", "observation_revisions")


def observation_schema():
    return [
        "CREATE TABLE neural_snapshots(experiment_id TEXT REFERENCES experiments(id), "
        "organism_id INTEGER,tick INTEGER,genome_id TEXT REFERENCES genomes(content_id), "
        "engine_hash TEXT,event_sequence INTEGER,payload_hash TEXT,payload BLOB, "
        "PRIMARY KEY(experiment_id,organism_id,tick))",
        "CREATE TABLE interventions(experiment_id TEXT REFERENCES experiments(id), "
        "id TEXT,tick INTEGER,kind TEXT,label TEXT,payload_version INTEGER,payload_json TEXT, "
        "PRIMARY KEY(experiment_id,id))",
        "CREATE TABLE observation_revisions(experiment_id TEXT PRIMARY KEY "
        "REFERENCES experiments(id),revision INTEGER NOT NULL)",
        "CREATE INDEX individuals_parent ON individuals(experiment_id,parent_id,id)",
        "CREATE INDEX individuals_death ON individuals(experiment_id,death_tick,id)",
        "CREATE INDEX individuals_birth ON individuals(experiment_id,born_tick,id)",
        "CREATE INDEX events_kind_tick ON events(experiment_id,kind,tick,event_seq)",
        "CREATE INDEX snapshots_tick ON neural_snapshots(experiment_id,tick,organism_id)",
        "CREATE INDEX interventions_tick ON interventions(experiment_id,tick,id)",
    ]


class ExperimentLock:
    """OS-held per-experiment lock, automatically released after process death."""

    def __init__(self, output: Path, identifier: str):
        import os

        directory = output / ".locks"
        directory.mkdir(exist_ok=True)
        self.stream = (directory / f"{identifier}.lock").open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise RuntimeError("Experiment is already open in another writer") from error

    def close(self):
        self.stream.close()


def migration_hook(stage):
    """Fault-injection boundary for recovery verification."""


def migrate(connection: sqlite3.Connection, database: Path):
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version not in {0, 1, 2}:
        raise ValueError("Unsupported database schema version")
    if connection.execute("SELECT count(*) FROM experiments").fetchone()[0]:
        backup = database.with_name(f"{database.stem}.pre-m4-{uuid.uuid4().hex}.sqlite3")
        with closing(sqlite3.connect(backup)) as destination:
            connection.backup(destination)
    statements = [
        "ALTER TABLE events ADD COLUMN event_seq INTEGER",
        "WITH numbered AS (SELECT event_id,ROW_NUMBER() OVER "
        "(PARTITION BY experiment_id ORDER BY event_id) AS seq FROM events) "
        "UPDATE events SET event_seq=(SELECT seq FROM numbered "
        "WHERE numbered.event_id=events.event_id)",
        "CREATE UNIQUE INDEX event_sequence ON events(experiment_id, event_seq)",
        "CREATE TABLE genomes(content_id TEXT PRIMARY KEY, payload BLOB NOT NULL)",
        "CREATE TABLE birth_genomes(experiment_id TEXT REFERENCES experiments(id), "
        "organism_id INTEGER, genome_id TEXT REFERENCES genomes(content_id), "
        "PRIMARY KEY(experiment_id, organism_id))",
        "CREATE TABLE experiment_heads(experiment_id TEXT PRIMARY KEY REFERENCES experiments(id), "
        "tick INTEGER, event_sequence INTEGER, engine_hash TEXT)",
        "CREATE TABLE experiment_origins(experiment_id TEXT PRIMARY KEY "
        "REFERENCES experiments(id), "
        "parent_experiment_id TEXT, fork_tick INTEGER, checkpoint_id TEXT)",
    ]
    if version in {1, 2}:
        statements = []
    geometry_statements = [
        "CREATE TABLE resource_geometry_history(experiment_id TEXT REFERENCES experiments(id), "
        "tick INTEGER,resource_id INTEGER,x REAL,y REAL, "
        "PRIMARY KEY(experiment_id,resource_id,tick))",
        "INSERT INTO resource_geometry_history SELECT experiment_id,tick,resource_id,x,y FROM "
        "(SELECT experiment_id,tick,resource_id,x,y, "
        "LAG(x) OVER (PARTITION BY experiment_id,resource_id ORDER BY tick) AS px, "
        "LAG(y) OVER (PARTITION BY experiment_id,resource_id ORDER BY tick) AS py "
        "FROM resources) "
        "WHERE px IS NULL OR x!=px OR y!=py",
    ]
    if version < 2:
        statements.extend(geometry_statements)
    statements.extend(observation_schema())
    connection.execute("BEGIN IMMEDIATE")
    try:
        for index, sql in enumerate(statements):
            connection.execute(sql)
            migration_hook(index)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def export_experiment(connection: sqlite3.Connection, identifier: str, path: Path):
    """Copy in SQLite, transactionally. Views avoid repeating UUIDs on every row.

    The resulting DB exposes the working schema's table names while physical tables
    omit the constant experiment_id. Global event rowids are replaced by logical sequences.
    No other experiment or unreferenced genome is ever copied.
    """
    uuid.UUID(identifier)
    if connection.in_transaction:
        raise RuntimeError("Commit the observation boundary before exporting")
    if path.exists():
        raise ValueError("Snapshot destination must be new")
    connection.execute("ATTACH DATABASE ? AS cp", (str(path),))
    try:
        connection.execute("BEGIN")
        # Normalize lifecycle fields in SELECT, not UPDATE: freed page bytes must not change hashes.
        connection.execute(
            "CREATE TABLE cp.experiments AS SELECT id,seed,simulator_version,started_at, "
            "NULL AS ended_at,'running' AS status,config_json,software_json, "
            "NULL AS summary_json FROM main.experiments WHERE id=?",
            (identifier,),
        )
        for table in (*TABLES, *OBSERVATION_TABLES):
            if table == "resources":
                connection.execute(
                    "CREATE TABLE cp._resource_energy(tick INTEGER,resource_id INTEGER,energy REAL)"
                )
                connection.execute(
                    "INSERT INTO cp._resource_energy SELECT tick,resource_id,energy "
                    "FROM main.resources "
                    "WHERE experiment_id=? ORDER BY tick,resource_id",
                    (identifier,),
                )
                connection.execute(
                    f"CREATE VIEW cp.resources AS SELECT '{identifier}' AS experiment_id, "
                    "e.tick,e.resource_id,g.x,g.y,e.energy FROM _resource_energy AS e "
                    "JOIN _resource_geometry_history AS g ON g.resource_id=e.resource_id AND "
                    "g.tick=(SELECT MAX(tick) FROM _resource_geometry_history AS prior "
                    "WHERE prior.resource_id=e.resource_id AND prior.tick<=e.tick)"
                )
                continue
            info = connection.execute(f"PRAGMA main.table_info({table})").fetchall()
            columns = [row[1] for row in info if row[1] not in {"experiment_id", "event_id"}]
            definitions = ",".join(f"{row[1]} {row[2]}" for row in info if row[1] in columns)
            connection.execute(f"CREATE TABLE cp._{table}({definitions})")
            order = {
                "samples": "tick",
                "resources": "tick,resource_id",
                "events": "event_seq",
                "individuals": "id",
                "birth_genomes": "organism_id",
                "resource_geometry_history": "resource_id,tick",
                "neural_snapshots": "organism_id,tick",
                "interventions": "tick,id",
            }.get(table, "rowid")
            selected = ",".join(columns)
            connection.execute(
                f"INSERT INTO cp._{table} SELECT {selected} FROM main.{table} "
                f"WHERE experiment_id=? ORDER BY {order}",
                (identifier,),
            )
            projection = ",".join(
                f"'{identifier}' AS experiment_id"
                if row[1] == "experiment_id"
                else "event_seq AS event_id"
                if row[1] == "event_id"
                else row[1]
                for row in info
            )
            connection.execute(f"CREATE VIEW cp.{table} AS SELECT {projection} FROM _{table}")
            if table == "resource_geometry_history":
                connection.execute(
                    "CREATE INDEX cp.geometry_lookup "
                    "ON _resource_geometry_history(resource_id,tick)"
                )
        connection.execute(
            "CREATE TABLE cp.genomes AS SELECT * FROM main.genomes WHERE content_id IN "
            "(SELECT genome_id FROM cp._birth_genomes) ORDER BY content_id"
        )
        connection.execute(f"PRAGMA cp.user_version = {SNAPSHOT_VERSION}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("DETACH DATABASE cp")


def import_experiment(
    connection,
    snapshot: Path,
    source_id: str,
    destination_id: str,
    checkpoint_id: str,
    fork_tick: int,
    metadata: list,
):
    connection.execute("ATTACH DATABASE ? AS cp", (snapshot.resolve().as_uri() + "?mode=ro",))
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO experiments VALUES (?,?,?,?,?,?,?,?,?)", [destination_id, *metadata[1:]]
        )
        connection.execute("INSERT OR IGNORE INTO genomes SELECT * FROM cp.genomes")
        for table in TABLES:
            if table == "experiment_origins":
                continue
            info = connection.execute(f"PRAGMA main.table_info({table})").fetchall()
            columns = [row[1] for row in info if row[1] != "event_id"]
            projection = ",".join("?" if col == "experiment_id" else col for col in columns)
            connection.execute(
                f"INSERT INTO main.{table} ({','.join(columns)}) "
                f"SELECT {projection} FROM cp.{table}",
                (destination_id,),
            )
        _merge_attached_observations(connection, destination_id, fork_tick)
        if source_id != destination_id:
            origin = (destination_id, source_id, fork_tick, checkpoint_id)
        else:
            origin = connection.execute("SELECT * FROM cp.experiment_origins").fetchone()
        if origin:
            connection.execute("INSERT INTO experiment_origins VALUES (?,?,?,?)", origin)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("DETACH DATABASE cp")


def validate_snapshot(path: Path, identifier: str):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in {103, SNAPSHOT_VERSION}:
            raise ValueError("Unsupported checkpoint SQLite schema")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint SQLite is corrupt")
        if connection.execute("SELECT id FROM experiments").fetchall() != [(identifier,)]:
            raise ValueError("Checkpoint contains unrelated experiments")
        for table in (*TABLES, *(OBSERVATION_TABLES if version == SNAPSHOT_VERSION else ())):
            if connection.execute(
                f"SELECT count(*) FROM {table} WHERE experiment_id!=?", (identifier,)
            ).fetchone()[0]:
                raise ValueError("Checkpoint contains unrelated rows")
        if connection.execute(
            "SELECT count(*) FROM genomes WHERE content_id NOT IN "
            "(SELECT genome_id FROM birth_genomes)"
        ).fetchone()[0]:
            raise ValueError("Checkpoint contains unrelated genomes")
        if connection.execute(
            "SELECT count(*) FROM birth_genomes WHERE genome_id NOT IN "
            "(SELECT content_id FROM genomes)"
        ).fetchone()[0]:
            raise ValueError("Checkpoint is missing genetic snapshots")
        if version == SNAPSHOT_VERSION:
            head = connection.execute(
                "SELECT tick,event_sequence,engine_hash FROM experiment_heads"
            )
            tick, sequence, engine_hash = head.fetchone()
            if connection.execute(
                "SELECT count(*) FROM neural_snapshots AS s LEFT JOIN birth_genomes AS b "
                "ON b.experiment_id=s.experiment_id AND b.organism_id=s.organism_id "
                "WHERE b.genome_id IS NULL OR b.genome_id!=s.genome_id OR s.tick>? "
                "OR s.event_sequence>? OR (s.tick=? AND s.engine_hash!=?)",
                (tick, sequence, tick, engine_hash),
            ).fetchone()[0]:
                raise ValueError("Snapshot observations do not belong to this trajectory")
            if connection.execute(
                "SELECT count(*) FROM interventions WHERE tick>?", (tick,)
            ).fetchone()[0]:
                raise ValueError("Checkpoint contains future interventions")


def observation_revision(connection, identifier):
    row = connection.execute(
        "SELECT revision FROM observation_revisions WHERE experiment_id=?", (identifier,)
    ).fetchone()
    return row[0] if row else 0


def _merge_attached_observations(connection, identifier, tick):
    if connection.execute("PRAGMA cp.user_version").fetchone()[0] != SNAPSHOT_VERSION:
        return
    for table, keys in (("neural_snapshots", ("organism_id", "tick")), ("interventions", ("id",))):
        columns = [r[1] for r in connection.execute(f"PRAGMA main.table_info({table})")]
        join = " AND ".join(f"a.{key}=b.{key}" for key in keys)
        value_columns = [c for c in columns if c != "experiment_id"]
        different = " OR ".join(f"a.{c} IS NOT b.{c}" for c in value_columns)
        if connection.execute(
            f"SELECT count(*) FROM main.{table} a JOIN cp.{table} b ON {join} "
            f"WHERE a.experiment_id=? AND ({different})",
            (identifier,),
        ).fetchone()[0]:
            raise ValueError("Conflicting observational history")
        projection = ",".join("?" if c == "experiment_id" else c for c in columns)
        cursor = connection.execute(
            f"INSERT OR IGNORE INTO main.{table} SELECT {projection} FROM cp.{table} WHERE tick<=?",
            (identifier, tick),
        )
        if cursor.rowcount:
            connection.execute(
                "INSERT INTO observation_revisions VALUES (?,1) ON CONFLICT(experiment_id) "
                "DO UPDATE SET revision=revision+1",
                (identifier,),
            )


def merge_observations(connection, snapshot, identifier, tick):
    connection.execute("ATTACH DATABASE ? AS cp", (snapshot.resolve().as_uri() + "?mode=ro",))
    try:
        connection.execute("BEGIN IMMEDIATE")
        _merge_attached_observations(connection, identifier, tick)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("DETACH DATABASE cp")


def history_digest(connection, identifier):
    """Logical M4 history, independent of SQLite layout and optional observations."""
    digest = hashlib.sha256()
    orders = {
        "samples": "tick",
        "resources": "tick,resource_id",
        "events": "event_seq",
        "individuals": "id",
        "birth_genomes": "organism_id",
        "resource_geometry_history": "resource_id,tick",
    }
    for table in ("experiments", *TABLES, "genomes"):
        columns = [
            r[1]
            for r in connection.execute(f"PRAGMA table_info({table})")
            if r[1] not in {"experiment_id", "event_id", "ended_at", "status", "summary_json"}
        ]
        if table == "genomes":
            query = (
                "SELECT content_id,hex(payload) FROM genomes WHERE content_id IN "
                "(SELECT genome_id FROM birth_genomes WHERE experiment_id=?) ORDER BY content_id"
            )
        else:
            key = "id" if table == "experiments" else "experiment_id"
            order = orders.get(table, columns[0])
            query = f"SELECT {','.join(columns)} FROM {table} WHERE {key}=? ORDER BY {order}"
        digest.update(table.encode())
        for row in connection.execute(query, (identifier,)):
            digest.update(json.dumps(list(row), separators=(",", ":"), allow_nan=False).encode())
            digest.update(b"\n")
    return digest.hexdigest()


def started_at():
    return datetime.now(UTC).isoformat()
