"""Atomic, self-contained data-only checkpoints and non-destructive resumption."""

import hashlib
import io
import json
import os
import platform
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile
from contextlib import closing, contextmanager
from functools import lru_cache
from importlib.resources import files
from pathlib import Path

import numpy as np

from .simulation import Simulation
from .state import canonical_json, fingerprint
from .storage import (
    ExperimentLock,
    export_experiment,
    file_hash,
    import_experiment,
    started_at,
    validate_snapshot,
)

FORMAT_VERSION = 1
MAX_STATE_BYTES = 64 * 1024 * 1024


@lru_cache(maxsize=1)
def compatibility():
    digest = hashlib.sha256()
    for name in (
        "configuration",
        "brain",
        "genome",
        "organism",
        "physics",
        "reproduction",
        "sensors",
        "signals",
        "simulation",
        "state",
        "world",
    ):
        resource = files("digital_ecosystem").joinpath(f"{name}.py")
        digest.update(name.encode())
        digest.update(resource.read_bytes().replace(b"\r\n", b"\n"))
    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "system": platform.system(),
        "machine": platform.machine(),
        "numpy_build": np.show_config(mode="dicts"),
        "cpu_features": dict(np._core._multiarray_umath.__cpu_features__),
        "numeric_environment": {
            name: os.environ.get(name)
            for name in (
                "NPY_DISABLE_CPU_FEATURES",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "MKL_CBWR",
            )
        },
        "numeric_core_sha256": digest.hexdigest(),
    }


def fault_hook(stage):
    """Named boundaries used by process-death and I/O fault verification."""


class DigestWriter:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()

    def write(self, block):
        self.hash.update(block)
        return self.stream.write(block)


def encode_state(archive, state, members):
    index = 0

    def encode(value):
        nonlocal index
        if isinstance(value, np.ndarray):
            name = f"arrays/{index:05d}.npy"
            index += 1
            with archive.open(name, "w") as stream:
                writer = DigestWriter(stream)
                np.lib.format.write_array(writer, value, allow_pickle=False)
                members[name] = writer.hash.hexdigest()
            return {"$array": name}
        if isinstance(value, dict):
            return {key: encode(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        return value

    payload = canonical_json(encode(state))
    members["state.json"] = hashlib.sha256(payload).hexdigest()
    archive.writestr("state.json", payload)


def decode_array(payload):
    stream = io.BytesIO(payload)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
    elif version == (2, 0):
        shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
    else:
        raise ValueError("Unsupported NPY version")
    expected = int(np.prod(shape, dtype=object)) * dtype.itemsize
    if dtype.hasobject or expected != len(payload) - stream.tell() or expected > MAX_STATE_BYTES:
        raise ValueError("Unsafe or invalid numerical payload")
    return (
        np.frombuffer(payload, dtype=dtype, offset=stream.tell())
        .copy()
        .reshape(shape, order="F" if fortran else "C")
    )


@contextmanager
def read_checkpoint(path: Path):
    """Validate before importing or replacing any running state. No arbitrary extraction."""
    path = Path(path)
    with tempfile.TemporaryDirectory(prefix="dlcp-load-") as temporary:
        snapshot = Path(temporary) / "experiment.sqlite3"
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                if len(set(names)) != len(names):
                    raise ValueError("Duplicate checkpoint members")
                if archive.getinfo("manifest.json").file_size > MAX_STATE_BYTES:
                    raise ValueError("Manifest is too large")
                manifest = json.loads(archive.read("manifest.json"))
                if manifest["format"] != FORMAT_VERSION:
                    raise ValueError("Unsupported checkpoint version")
                if manifest["compatibility"] != compatibility():
                    raise ValueError("Checkpoint numerical environment is incompatible")
                uuid.UUID(manifest["experiment_id"])
                uuid.UUID(manifest["checkpoint_id"])
                members = manifest["members"]
                if set(names) != {*members, "manifest.json"}:
                    raise ValueError("Missing or unexpected checkpoint members")
                if not {"state.json", "experiment.sqlite3"} <= members.keys():
                    raise ValueError("Incomplete checkpoint")
                decoded = {}
                for name, expected_hash in members.items():
                    if name not in {"state.json", "experiment.sqlite3"} and not re.fullmatch(
                        r"arrays/\d{5}\.npy", name
                    ):
                        raise ValueError("Invalid archive member name")
                    if (
                        name != "experiment.sqlite3"
                        and archive.getinfo(name).file_size > MAX_STATE_BYTES
                    ):
                        raise ValueError("State member is too large")
                    digest = hashlib.sha256()
                    with archive.open(name) as source:
                        if name == "experiment.sqlite3":
                            with snapshot.open("wb") as destination:
                                for block in iter(lambda: source.read(1024 * 1024), b""):
                                    digest.update(block)
                                    destination.write(block)
                        else:
                            payload = source.read()
                            digest.update(payload)
                            decoded[name] = (
                                json.loads(payload)
                                if name == "state.json"
                                else decode_array(payload)
                            )
                    if digest.hexdigest() != expected_hash:
                        raise ValueError(f"Checkpoint checksum mismatch: {name}")

                def decode(value):
                    if isinstance(value, dict):
                        if set(value) == {"$array"}:
                            return decoded[value["$array"]]
                        return {key: decode(item) for key, item in value.items()}
                    if isinstance(value, list):
                        return [decode(item) for item in value]
                    return value

                state = decode(decoded["state.json"])
                if fingerprint(state) != manifest["state_hash"]:
                    raise ValueError("Checkpoint state fingerprint mismatch")
                simulation = Simulation.from_state(state)
                if json.loads(manifest["metadata"][6]) != simulation.config.to_dict():
                    raise ValueError("Checkpoint configuration and experiment metadata disagree")
                if simulation.tick != manifest["tick"]:
                    raise ValueError("Checkpoint cursor mismatch")
                validate_snapshot(snapshot, manifest["experiment_id"])
                with closing(sqlite3.connect(snapshot)) as connection:
                    head = connection.execute(
                        "SELECT tick,event_sequence,engine_hash FROM experiment_heads"
                    ).fetchone()
                if head != (
                    simulation.tick,
                    simulation.event_sequence,
                    simulation.state_fingerprint(),
                ):
                    raise ValueError("SQLite and numerical state are not from the same boundary")
                yield simulation, manifest, snapshot
        except (
            zipfile.BadZipFile,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            sqlite3.Error,
            OverflowError,
        ) as error:
            raise ValueError(f"Invalid checkpoint: {error}") from error


class CheckpointManager:
    def __init__(self, logger):
        self.logger = logger
        self.directory = logger.output / "checkpoints" / logger.experiment_id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.last_path = None
        self.last_hash = None
        self.measurements = []

    def maybe_save(self):
        simulation = self.logger.simulation
        config = simulation.config.checkpoint
        if config.enabled and simulation.tick and simulation.tick % config.interval_ticks == 0:
            return self.save("automatic")
        return None

    def save(self, reason="manual") -> Path:
        try:
            return self._save(reason)
        except sqlite3.Error as error:
            raise RuntimeError(f"Checkpoint SQLite export failed: {error}") from error

    def _save(self, reason) -> Path:
        logger, simulation = self.logger, self.logger.simulation
        if logger.closed:
            raise RuntimeError("Cannot checkpoint a closed logger")
        recorded_config = logger.connection.execute(
            "SELECT config_json FROM experiments WHERE id=?", (logger.experiment_id,)
        ).fetchone()[0]
        if json.loads(recorded_config) != simulation.config.to_dict():
            raise ValueError("Configuration changed during experiment; start a new experiment")
        started = time.perf_counter()
        engine_hash = logger.flush()
        fault_hook("after_flush")
        if self.last_path is not None and self.last_path.exists() and self.last_hash == engine_hash:
            return self.last_path
        checkpoint_id = str(uuid.uuid4())
        final = self.directory / f"tick-{simulation.tick:012d}-{checkpoint_id}.dlcp"
        metadata = list(
            logger.connection.execute(
                "SELECT * FROM experiments WHERE id=?", (logger.experiment_id,)
            ).fetchone()
        )
        with tempfile.TemporaryDirectory(prefix=".saving-", dir=self.directory) as temporary:
            temporary = Path(temporary)
            snapshot = temporary / "experiment.sqlite3"
            export_start = time.perf_counter()
            export_experiment(logger.connection, logger.experiment_id, snapshot)
            export_end = time.perf_counter()
            fault_hook("after_export")
            state = simulation.to_state()
            state_hash = fingerprint(state)
            serialization_end = time.perf_counter()
            members = {"experiment.sqlite3": file_hash(snapshot)}
            partial = temporary / "archive.part"
            with zipfile.ZipFile(
                partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True
            ) as archive:
                encode_state(archive, state, members)
                fault_hook("after_arrays")
                archive.write(snapshot, "experiment.sqlite3")
                manifest = {
                    "format": FORMAT_VERSION,
                    "checkpoint_id": checkpoint_id,
                    "experiment_id": logger.experiment_id,
                    "created_at": started_at(),
                    "tick": simulation.tick,
                    "reason": reason,
                    "compatibility": compatibility(),
                    "members": members,
                    "state_hash": state_hash,
                    "metadata": metadata,
                    "last_sample": logger.last_sample,
                }
                archive.writestr("manifest.json", canonical_json(manifest))
            compression_end = time.perf_counter()
            fault_hook("after_archive")
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Written checkpoint failed CRC verification")
            with partial.open("r+b") as stream:
                os.fsync(stream.fileno())
            synchronization_end = time.perf_counter()
            fault_hook("before_publish")
            os.replace(partial, final)
            if os.name != "nt":
                descriptor = os.open(self.directory, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            self.last_path, self.last_hash = final, engine_hash
            fault_hook("after_publish")
            fault_hook("before_rotation")
            predecessors = sorted(
                (p for p in self.directory.glob("*.dlcp") if p != final),
                key=lambda p: (p.stat().st_mtime_ns, p.name),
                reverse=True,
            )
            for path in predecessors[simulation.config.checkpoint.previous_versions :]:
                if path.resolve().parent != self.directory.resolve() or path.is_symlink():
                    raise ValueError("Refusing checkpoint rotation outside its experiment")
                path.unlink()
            fault_hook("after_rotation")
            measurement = {
                "tick": simulation.tick,
                "reason": reason,
                "path": str(final),
                "bytes": final.stat().st_size,
                "sqlite_bytes": snapshot.stat().st_size,
                "export_seconds": export_end - export_start,
                "serialization_seconds": serialization_end - export_end,
                "compression_seconds": compression_end - serialization_end,
                "synchronization_seconds": synchronization_end - compression_end,
                "total_seconds": time.perf_counter() - started,
            }
            self.measurements.append(measurement)
        return final


def resume(path: Path, output: Path | None = None):
    path = Path(path)
    destination = Path(output) if output is not None else path.resolve().parent
    with read_checkpoint(path) as (simulation, manifest, snapshot):
        return resume_prepared(simulation, manifest, snapshot, destination)


def resume_prepared(simulation, manifest, snapshot, destination):
    from .experiment_logger import ExperimentLogger

    logger = ExperimentLogger.__new__(ExperimentLogger)
    logger.simulation, logger.output = simulation, destination
    destination.mkdir(parents=True, exist_ok=True)
    logger.database = destination / "lab.sqlite3"
    logger.closed = False
    identifier = manifest["experiment_id"]
    logger.experiment_id = identifier
    logger.lock = ExperimentLock(destination, identifier)
    try:
        logger.connection = sqlite3.connect(logger.database, uri=True)
        logger.connection.execute("PRAGMA foreign_keys=ON")
        logger._schema()
        from .storage import migrate

        migrate(logger.connection, logger.database)
        existing = logger.connection.execute(
            "SELECT id FROM experiments WHERE id=?", (identifier,)
        ).fetchone()
        if existing:
            current_head = logger.connection.execute(
                "SELECT tick,event_sequence,engine_hash FROM experiment_heads "
                "WHERE experiment_id=?",
                (identifier,),
            ).fetchone()
            match = current_head == (
                simulation.tick,
                simulation.event_sequence,
                simulation.state_fingerprint(),
            )
            if match:
                comparison = Path(tempfile.mkdtemp(prefix="dlcp-compare-"))
                try:
                    export_experiment(logger.connection, identifier, comparison / "history.sqlite3")
                    match = (
                        file_hash(comparison / "history.sqlite3")
                        == (manifest["members"]["experiment.sqlite3"])
                    )
                finally:
                    (comparison / "history.sqlite3").unlink(missing_ok=True)
                    comparison.rmdir()
            if not match:
                logger.lock.close()
                logger.experiment_id = str(uuid.uuid4())
                logger.lock = ExperimentLock(destination, logger.experiment_id)
        if not existing or logger.experiment_id != identifier:
            import_experiment(
                logger.connection,
                snapshot,
                identifier,
                logger.experiment_id,
                manifest["checkpoint_id"],
                simulation.tick,
                manifest["metadata"],
            )
        logger.last_sample = manifest["last_sample"]
        logger.samples_since_commit = 0
        logger.archived_id = max(simulation.records, default=0)
        logger.last_resource_positions = simulation.world.resource_positions.copy()
        logger.committed_hash = simulation.state_fingerprint()
        logger.connection.execute(
            "UPDATE experiments SET status='running', ended_at=NULL WHERE id=?",
            (logger.experiment_id,),
        )
        logger.connection.commit()
        return simulation, logger
    except BaseException:
        if hasattr(logger, "connection"):
            logger.connection.close()
        logger.lock.close()
        raise
