"""Versioned observational storage and experiment-scoped SQLite transport."""

import hashlib
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2
SNAPSHOT_VERSION = 103
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
    if version not in {0, 1}:
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
    if version == 1:
        statements = []
    statements.extend(
        [
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
    )
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
        for table in TABLES:
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
        if connection.execute("PRAGMA user_version").fetchone()[0] != SNAPSHOT_VERSION:
            raise ValueError("Unsupported checkpoint SQLite schema")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint SQLite is corrupt")
        if connection.execute("SELECT id FROM experiments").fetchall() != [(identifier,)]:
            raise ValueError("Checkpoint contains unrelated experiments")
        for table in TABLES:
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


def started_at():
    return datetime.now(UTC).isoformat()
