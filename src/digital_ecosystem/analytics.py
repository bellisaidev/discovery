"""Bounded, read-only historical analytics. No simulation or Pygame dependency."""

import itertools
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np

from .observations import ExperimentReader, dictionaries

GROUPS = {
    "Popolazione": [
        ("Popolazione", ("population",)),
        ("Generazioni nella popolazione viva", ("mean_generation", "max_generation")),
    ],
    "Eventi": [
        ("Nascite / morti cumulative", ("births", "deaths")),
        ("Eventi per secondo simulato", ("birth_rate", "death_rate")),
        ("Cause di morte registrate (cumulative)", ("death_energy", "death_age", "death_other")),
    ],
    "Energia": [
        ("Raccolta / dissipata", ("harvested_energy", "dissipated_energy")),
        ("Flussi per secondo", ("harvest_rate", "consumption_rate")),
        (
            "Dissipazione per categoria",
            (
                "metabolic_dissipation",
                "action_dissipation",
                "reproductive_dissipation",
                "death_dissipation",
            ),
        ),
        ("Riserve / rigenerazione", ("total_energy", "resource_energy", "regenerated_energy")),
    ],
    "Longevita": [
        ("Vite concluse: media / mediana per intervallo", ("lifespan_mean", "lifespan_median")),
        ("Morti per intervallo", ("lifespan_count",)),
    ],
    "Reti": [
        ("Complessita strutturale: neuroni medi", ("mean_neurons",)),
        ("Complessita strutturale: connessioni medie", ("mean_connections",)),
    ],
    "Diversita": [
        ("Diversita genetica approssimata", ("genetic_diversity",)),
        ("Linee / genomi distinti", ("lineages", "distinct_genomes")),
    ],
}
RATES = {
    "birth_rate": "births",
    "death_rate": "deaths",
    "harvest_rate": "harvested_energy",
    "consumption_rate": "dissipated_energy",
}
CAUSES = {"death_energy": "energy_exhaustion", "death_age": "age_limit", "death_other": None}
LABELS = {
    "population": "popolazione",
    "mean_generation": "generazione media (vivi)",
    "max_generation": "generazione massima (vivi)",
    "births": "nascite",
    "deaths": "morti",
    "birth_rate": "nascite/s",
    "death_rate": "morti/s",
    "harvested_energy": "raccolta",
    "dissipated_energy": "dissipata",
    "harvest_rate": "raccolta/s",
    "consumption_rate": "dissipata/s",
    "metabolic_dissipation": "metabolismo",
    "action_dissipation": "azioni",
    "reproductive_dissipation": "riproduzione",
    "death_dissipation": "residuo alla morte",
    "total_energy": "corpi + depositi",
    "resource_energy": "depositi",
    "regenerated_energy": "rigenerata",
    "mean_neurons": "neuroni (input e output inclusi)",
    "mean_connections": "connessioni",
    "genetic_diversity": "distanza genetica",
    "lineages": "linee",
    "distinct_genomes": "genomi distinti",
    "lifespan_mean": "media (s)",
    "lifespan_median": "mediana (s)",
    "lifespan_count": "decessi",
    "death_energy": "esaurimento energia",
    "death_age": "limite eta",
    "death_other": "altre cause",
}


class HistoricalReader(ExperimentReader):
    """Cursor-aware adapter: an earlier cursor never reveals future individuals or states."""

    def __init__(self, source, cursor=None):
        super().__init__(
            source.database, connection=source.connection, experiment_id=source.experiment_id
        )
        self.cursor = cursor

    def individual(self, identifier, tick=None):
        if self.cursor is not None:
            tick = self.cursor if tick is None else min(tick, self.cursor)
        return super().individual(identifier, tick)

    def genome(self, identifier):
        if self.cursor is not None and self.individual(identifier) is None:
            return None
        return super().genome(identifier)

    def snapshots(self, identifier, *, after=-1, end=2**63 - 1, limit=100):
        if self.cursor is not None:
            end = min(end, self.cursor)
        return super().snapshots(identifier, after=after, end=end, limit=limit)

    def snapshot(self, identifier, tick):
        if self.cursor is not None and tick > self.cursor:
            return None
        return super().snapshot(identifier, tick)


def nearest_sample(reader, tick):
    """Actual preceding sample, not an interpolation or a rounded display point."""
    rows = dictionaries(
        reader.connection.execute(
            "SELECT * FROM samples WHERE experiment_id=? AND tick<=? ORDER BY tick DESC LIMIT 1",
            (reader.experiment_id, tick),
        )
    )
    return rows[0] if rows else None


def sample_bounds(reader):
    values = []
    for order in ("ASC", "DESC"):
        row = reader.connection.execute(
            f"SELECT tick FROM samples WHERE experiment_id=? ORDER BY tick {order} LIMIT 1",
            (reader.experiment_id,),
        ).fetchone()
        values.append(row[0] if row else None)
    return tuple(values)


def sample_values(reader, tick, keys):
    sample = nearest_sample(reader, tick)
    if sample is None:
        return None, {}
    previous = nearest_sample(reader, sample["tick"] - 1) if any(k in RATES for k in keys) else None
    causes = json.loads(sample.get("death_causes") or "{}")
    result = {}
    for key in keys:
        value = sample.get(key)
        if key in CAUSES and sample.get("death_causes") is not None:
            value = (
                causes.get(CAUSES[key], 0)
                if CAUSES[key] is not None
                else sum(
                    v for k, v in causes.items() if k not in {"energy_exhaustion", "age_limit"}
                )
            )
        if key in RATES:
            duration = sample["simulated_time"] - previous["simulated_time"] if previous else 0
            value = (
                (sample[RATES[key]] - previous[RATES[key]]) / duration
                if duration > 0
                and sample.get(RATES[key]) is not None
                and previous.get(RATES[key]) is not None
                else None
            )
        result[key] = value
    return sample, result


def genealogy_page(reader, cursor, *, parent=None, after=0, lineage=None, limit=100):
    where = "parent_id IS NULL" if parent is None else "parent_id=?"
    values = [reader.experiment_id, cursor, after]
    if parent is not None:
        values.append(parent)
    if lineage is not None:
        where += " AND lineage_id=?"
        values.append(lineage)
    values.append(min(limit, 500))
    return dictionaries(
        reader.connection.execute(
            "SELECT id,parent_id,lineage_id,generation,born_tick,"
            "CASE WHEN death_tick<=? THEN death_tick END AS death_tick FROM individuals "
            f"WHERE experiment_id=? AND born_tick<=? AND id>? AND {where} ORDER BY id LIMIT ?",
            [cursor, *values],
        )
    )


class GenealogyTree:
    """Progressively loaded tree; the viewport cache never contains more than 500 nodes."""

    def __init__(self, reader, cursor, lineage=None, root=None):
        self.reader, self.cursor, self.lineage = reader, cursor, lineage
        self.nodes = {}
        self.expanded = set()
        self.last_parent = None
        self.limit_reached = False
        if root is None:
            self.more(None)
        else:
            row = HistoricalReader(reader, cursor).individual(root)
            if row:
                self.nodes[root] = row

    def more(self, parent):
        self.last_parent = parent
        after = max((i for i, r in self.nodes.items() if r["parent_id"] == parent), default=0)
        room = 500 - len(self.nodes)
        self.limit_reached = room <= 0
        if room <= 0:
            return
        for row in genealogy_page(
            self.reader,
            self.cursor,
            parent=parent,
            after=after,
            lineage=self.lineage,
            limit=min(100, room),
        ):
            self.nodes[row["id"]] = row
        if parent is not None:
            self.expanded.add(parent)

    def toggle(self, identifier):
        if identifier not in self.expanded:
            self.more(identifier)
            return
        pending = [identifier]
        while pending:
            parent = pending.pop()
            children = [
                i for i, r in self.nodes.items() if r["parent_id"] == parent and i != identifier
            ]
            pending.extend(children)
            for child in children:
                del self.nodes[child]
                self.expanded.discard(child)
        self.expanded.discard(identifier)
        self.limit_reached = False

    def rows(self):
        children = {}
        for identifier, row in self.nodes.items():
            parent = row["parent_id"] if row["parent_id"] in self.nodes else None
            children.setdefault(parent, []).append(identifier)
        result, seen = [], set()

        def visit(identifier, depth):
            if identifier in seen:
                return
            seen.add(identifier)
            result.append(dict(self.nodes[identifier], depth=depth))
            for child in sorted(children.get(identifier, ())):
                visit(child, depth + 1)

        for identifier in sorted(children.get(None, ())):
            visit(identifier, 0)
        return result


def metrics(group):
    return tuple(dict.fromkeys(key for _, series in GROUPS[group] for key in series))


class Envelope:
    """At most first/last/min/max per metric and pixel bucket; original rows stay in SQLite."""

    def __init__(self, start, end, width, keys):
        self.start, self.end, self.width, self.keys = start, end, min(max(1, width), 1000), keys
        self.buckets = {}
        self.count = 0

    def add(self, row):
        if not self.start <= row["tick"] <= self.end:
            return
        bucket = min(
            self.width - 1,
            (row["tick"] - self.start) * self.width // max(1, self.end - self.start + 1),
        )
        values = self.buckets.get(bucket)
        if values is None:
            values = {"first": row, "last": row, "extrema": {}}
            self.buckets[bucket] = values
        values["last"] = row
        for key in self.keys:
            value = row.get(key)
            if value is None:
                continue
            low, high = values["extrema"].get(key, (row, row))
            values["extrema"][key] = (
                row if value < low[key] else low,
                row if value > high[key] else high,
            )
        self.count += 1

    def rows(self):
        result = {}
        for bucket in self.buckets.values():
            for row in (
                bucket["first"],
                bucket["last"],
                *(r for pair in bucket["extrema"].values() for r in pair),
            ):
                result[row["tick"]] = row
        return [result[tick] for tick in sorted(result)]


def sampled_series(reader, group, start, end, width, cutoff, overlay=(), sample_interval=30):
    keys = metrics(group)
    available = {r[1] for r in reader.connection.execute("PRAGMA table_info(samples)")}
    columns = [
        "tick",
        "simulated_time",
        *dict.fromkeys("death_causes" if k in CAUSES else RATES.get(k, k) for k in keys),
    ]
    columns = [c for c in columns if c in available]
    selected = ",".join(columns)
    previous_rows = reader.connection.execute(
        f"SELECT {selected} FROM samples WHERE experiment_id=? AND tick<? "
        "AND tick<=? ORDER BY tick DESC LIMIT 1",
        (reader.experiment_id, start, cutoff),
    ).fetchall()
    previous = dict(zip(columns, previous_rows[0], strict=True)) if previous_rows else None

    def pages():
        after = start - 1
        while True:
            page = reader.connection.execute(
                f"SELECT {selected} FROM samples WHERE experiment_id=? "
                "AND tick>? AND tick<=? ORDER BY tick LIMIT 1000",
                (reader.experiment_id, after, min(end, cutoff)),
            ).fetchall()
            if not page:
                break
            yield from page
            after = page[-1][0]

    tail = sorted((row for row in overlay if cutoff < row["tick"] <= end), key=lambda r: r["tick"])
    envelope = Envelope(start, end, width, keys)
    segment = 0
    for item in itertools.chain(pages(), tail):
        row = item if isinstance(item, dict) else dict(zip(columns, item, strict=True))
        if previous and row["tick"] - previous["tick"] > sample_interval:
            segment += 1
        derived = {"tick": row["tick"], "simulated_time": row["simulated_time"], "segment": segment}
        causes = json.loads(row["death_causes"]) if row.get("death_causes") is not None else {}
        for key in keys:
            value = row.get(key)
            if key in CAUSES and row.get("death_causes") is not None:
                value = (
                    causes.get(CAUSES[key], 0)
                    if CAUSES[key] is not None
                    else sum(
                        v for k, v in causes.items() if k not in {"energy_exhaustion", "age_limit"}
                    )
                )
            if key in RATES:
                source = RATES[key]
                duration = row["simulated_time"] - previous["simulated_time"] if previous else 0
                value = (
                    (row[source] - previous[source]) / duration
                    if duration > 0
                    and row.get(source) is not None
                    and previous.get(source) is not None
                    else None
                )
            derived[key] = value
        envelope.add(derived)
        previous = row
    return envelope.rows(), envelope.count


def longevity(reader, start, end, dt, width=50):
    # A lifespan is completed only when its death was observed at/before this cursor.
    count, mean, low, high = reader.connection.execute(
        "SELECT count(*),avg(lifespan),min(lifespan),max(lifespan) FROM individuals "
        "WHERE experiment_id=? AND death_tick>=? AND death_tick<=? AND lifespan IS NOT NULL",
        (reader.experiment_id, start, end),
    ).fetchone()
    median = None
    if count:
        middle = reader.connection.execute(
            "SELECT lifespan FROM individuals WHERE experiment_id=? AND death_tick>=? "
            "AND death_tick<=? AND lifespan IS NOT NULL ORDER BY lifespan LIMIT ? OFFSET ?",
            (reader.experiment_id, start, end, 2 if count % 2 == 0 else 1, (count - 1) // 2),
        ).fetchall()
        median = float(np.mean([r[0] for r in middle]))
    living, mean_age = reader.connection.execute(
        "SELECT count(*),avg((?-born_tick)*?) FROM individuals WHERE experiment_id=? "
        "AND born_tick<=? AND (death_tick IS NULL OR death_tick>?)",
        (end, dt, reader.experiment_id, end, end),
    ).fetchone()
    span = max(1, end - start + 1)
    bins = min(max(1, width), 100, span)
    rows = reader.connection.execute(
        "SELECT min(?-1,CAST((death_tick-?)*?/? AS INTEGER)) AS bucket, lifespan "
        "FROM individuals WHERE experiment_id=? AND death_tick>=? AND death_tick<=? "
        "AND lifespan IS NOT NULL ORDER BY bucket,lifespan",
        (bins, start, bins, span, reader.experiment_id, start, end),
    )
    points = []
    for bucket, entries in itertools.groupby(rows, key=lambda r: r[0]):
        values = np.fromiter((r[1] for r in entries), dtype=float)
        tick = min(end, start + math.ceil((bucket + 1) * span / bins) - 1)
        points.append(
            {
                "tick": tick,
                "simulated_time": tick * dt,
                "lifespan_mean": float(np.mean(values)),
                "lifespan_median": float(np.median(values)),
                "lifespan_count": len(values),
                "start_tick": start + math.ceil(bucket * span / bins),
            }
        )
    by_tick = {point["tick"]: point for point in points}
    points = []
    if end >= start:
        for bucket in range(bins):
            tick = min(end, start + math.ceil((bucket + 1) * span / bins) - 1)
            if tick < start or (points and tick == points[-1]["tick"]):
                continue
            points.append(
                by_tick.get(
                    tick,
                    {
                        "tick": tick,
                        "simulated_time": tick * dt,
                        "lifespan_mean": None,
                        "lifespan_median": None,
                        "lifespan_count": 0,
                        "start_tick": start + math.ceil(bucket * span / bins),
                    },
                )
            )
    histogram = []
    if count:
        bin_size = max(1e-12, (high - low) / 12)
        histogram = dictionaries(
            reader.connection.execute(
                "SELECT min(11,CAST((lifespan-?)/? AS INTEGER)) AS bin,count(*) AS count "
                "FROM individuals WHERE experiment_id=? AND death_tick>=? AND death_tick<=? "
                "AND lifespan IS NOT NULL GROUP BY bin ORDER BY bin",
                (low, bin_size, reader.experiment_id, start, end),
            )
        )
    return points, {
        "completed": count,
        "mean": mean,
        "median": median,
        "living_censored": living,
        "living_mean_age": mean_age,
        "histogram": histogram,
        "histogram_min": low,
        "histogram_max": high,
        "tick": end,
    }


@dataclass(frozen=True)
class DataRequest:
    database: str
    experiment_id: str
    group: str
    start: int
    end: int
    cutoff: int
    cursor: int
    width: int = 500
    overlay: tuple = ()


def load_analytics(request, cancel=None):
    reader = ExperimentReader(request.database, experiment_id=request.experiment_id)
    try:
        if cancel is not None:
            reader.connection.set_progress_handler(lambda: int(cancel.is_set()), 10000)
        metadata = reader.metadata()
        config = json.loads(metadata["config_json"])
        dt = config["world"]["dt"]
        interval = config.get("logging", {}).get("sample_interval", 30)
        count = None
        life = None
        individual_tick = min(request.cursor, request.cutoff)
        if request.group == "Longevita":
            points, life = longevity(reader, request.start, individual_tick, dt)
        else:
            points, count = sampled_series(
                reader,
                request.group,
                request.start,
                request.end,
                request.width,
                request.cutoff,
                request.overlay,
                interval,
            )
        sample = nearest_sample(reader, min(request.cursor, request.cutoff))
        for row in request.overlay:
            if row["tick"] <= request.cursor and (sample is None or row["tick"] > sample["tick"]):
                sample = row
        origins = None
        if "experiment_origins" in reader.tables:
            rows = dictionaries(
                reader.connection.execute(
                    "SELECT * FROM experiment_origins WHERE experiment_id=?",
                    (reader.experiment_id,),
                )
            )
            origins = rows[0] if rows else None
        causes = json.loads(sample.get("death_causes") or "{}") if sample else {}
        generations = json.loads(sample.get("generation_distribution") or "{}") if sample else {}
        extinction = None
        if sample and sample["population"] == 0:
            alive = reader.connection.execute(
                "SELECT count(*) FROM individuals WHERE experiment_id=? AND born_tick<=? "
                "AND (death_tick IS NULL OR death_tick>?)",
                (reader.experiment_id, individual_tick, individual_tick),
            ).fetchone()[0]
            if not alive:
                extinction = reader.connection.execute(
                    "SELECT max(death_tick) FROM individuals "
                    "WHERE experiment_id=? AND death_tick<=?",
                    (reader.experiment_id, individual_tick),
                ).fetchone()[0]
        interventions = reader.interventions(request.start, min(request.end, request.cutoff))
        intervention_total = (
            reader.connection.execute(
                "SELECT count(*) FROM interventions WHERE experiment_id=? AND tick>=? AND tick<=?",
                (reader.experiment_id, request.start, min(request.end, request.cutoff)),
            ).fetchone()[0]
            if "interventions" in reader.tables
            else 0
        )
        return {
            "request": request,
            "points": points,
            "source_samples": count,
            "sample": sample,
            "metadata": metadata,
            "dt": dt,
            "sample_interval": interval,
            "life": life,
            "origin": origins,
            "causes": causes,
            "generations": generations,
            "extinction_tick": extinction,
            "interventions": interventions,
            "intervention_total": intervention_total,
            "individual_tick": individual_tick,
        }
    finally:
        reader.close()


class AnalyticsWorker:
    """One running request and one replaceable pending request, with cancellation."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lab-reader")
        self.future = None
        self.cancel = None
        self.pending = None
        self.generation = 0
        self.active_generation = 0
        self.closed = False

    def request(self, request):
        if self.closed:
            return
        self.generation += 1
        self.pending = request
        if self.future and not self.future.done():
            self.cancel.set()
        self._start()

    def _start(self):
        if self.pending is not None and self.future is None:
            self.cancel = threading.Event()
            self.active_generation = self.generation
            self.future = self.executor.submit(load_analytics, self.pending, self.cancel)
            self.pending = None

    def poll(self):
        if self.future is None or not self.future.done():
            return None
        result = None
        try:
            value = self.future.result()
            if self.active_generation == self.generation:
                result = (value, None)
        except Exception as error:
            if self.active_generation == self.generation:
                result = (None, str(error))
        self.future = None
        self._start()
        return result

    def close(self):
        self.closed = True
        if self.cancel:
            self.cancel.set()
        self.pending = None
        self.executor.shutdown(wait=True, cancel_futures=True)
