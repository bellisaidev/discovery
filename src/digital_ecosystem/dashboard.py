"""Integrated desktop dashboard and archive browser; all mutations stay in session callbacks."""

import json
import math
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pygame

from .analytics import (
    GROUPS,
    LABELS,
    AnalyticsWorker,
    DataRequest,
    GenealogyTree,
    HistoricalReader,
    sample_bounds,
    sample_values,
)
from .observations import ExperimentReader
from .renderer import Renderer

COLORS = [(91, 211, 216), (244, 185, 96), (193, 143, 237), (122, 211, 145), (235, 132, 155)]


class DashboardRenderer(Renderer):
    def __init__(self, simulation=None, *, browse=None, experiment_id=None, **callbacks):
        # The display context never constructs a Simulation or consumes its RNG.
        context = simulation or SimpleNamespace(
            seed=0, tick=0, config=SimpleNamespace(world=SimpleNamespace(dt=1 / 30))
        )
        super().__init__(context, **callbacks)
        pygame.display.set_caption("Digital Life Lab — Neural Inspector e Dashboard")
        self.current_reader = self.on_reader
        self.on_reader = self.reader
        self.browser_only = simulation is None
        self.archive_reader = None
        self.library = None
        self.archive_path = str(browse or "experiments/lab.sqlite3")
        self.path_active = False
        self.library_rows = []
        self.library_after = ""
        self.library_scroll = 0
        self.group = "Popolazione"
        self.worker = AnalyticsWorker()
        self.data = None
        self.request_key = None
        self.request_time = 0
        self.range = None
        self.cursor = None
        self.follow = True
        self.seconds = False
        self.hidden = set()
        self.plots = []
        self.legends = []
        self.drag_tick = None
        self.interval_start = None
        self.hover_tick = None
        self.hover_pos = None
        self.source_bounds = (0, 0)
        self.genealogy = []
        self.genealogy_scroll = 0
        self.genealogy_lineage = None
        self.genealogy_parent = None
        self.genealogy_after = 0
        self.lineage_text = ""
        self.lineage_active = False
        self.genealogy_rows = []
        self.genealogy_key = None
        self.tree = None
        self.tree_root = None
        self.intervention_index = 0
        self.generation_offset = 0
        self.payload_scroll = 0
        self.paused = self.browser_only
        if browse is not None:
            self.open_database(browse, experiment_id)

    def reader(self):
        source = (
            self.archive_reader
            if self.archive_active
            else (self.current_reader() if self.current_reader else None)
        )
        if source is None:
            return None
        cap = self.cursor if self.archive_active or not self.follow else None
        return HistoricalReader(source, cap)

    def source(self):
        return (
            self.archive_reader
            if self.archive_active
            else (self.current_reader() if self.current_reader else None)
        )

    def reset_source(self):
        self.data, self.request_key, self.range, self.cursor = None, None, None, None
        self.interval_start, self.hover_tick, self.hover_pos = None, None, None
        self.follow = True
        self.selected = None
        self.inspector.reset()
        self.genealogy = []
        self.genealogy_key = None
        self.worker.generation += 1
        self.worker.pending = None
        if self.worker.cancel:
            self.worker.cancel.set()

    def open_database(self, path, identifier=None):
        replacement = ExperimentReader(path, experiment_id=identifier)
        rows = replacement.experiments()
        if self.library:
            self.library.close()
        self.library = replacement
        if self.archive_reader:
            self.archive_reader.close()
            self.archive_reader = None
        self.archive_active = True
        self.archive_path = str(Path(path))
        self.library_rows, self.library_after = rows, ""
        self.library_scroll = 0
        self.paused, self.accumulator = True, 0
        self.view = "library"
        if identifier is not None:
            self.open_experiment(identifier)

    def open_experiment(self, identifier):
        replacement = ExperimentReader(self.archive_path, experiment_id=identifier)
        if self.archive_reader:
            self.archive_reader.close()
        self.archive_reader = replacement
        self.seed_text = str(replacement.metadata()["seed"])
        self.archive_active = True
        self.paused, self.accumulator = True, 0
        self.reset_source()
        self.view = "dashboard"

    def command(self, command):
        try:
            self._command(command)
        except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
            self.message = str(error)

    def _command(self, command):
        if command == "dashboard":
            self.view = "dashboard"
        elif command == "database":
            self.open_database(self.archive_path)
        elif command.startswith("experiment:"):
            self.open_experiment(command.split(":", 1)[1])
        elif command == "experiments_next":
            after = self.library_rows[-1]["id"] if self.library_rows else ""
            rows = self.library.experiments(after=after)
            self.library_rows = rows or self.library.experiments()
            self.library_scroll = 0
        elif command == "current":
            if self.browser_only:
                self.message = "Modalita consultazione: nessuna simulazione corrente"
                return
            self.archive_active = False
            self.seed_text = str(self.simulation.seed)
            self.paused, self.accumulator = True, 0
            self.reset_source()
            self.view = "world"
        elif command.startswith("group:"):
            self.group = command.split(":", 1)[1]
            self.request_key = None
        elif command == "axis":
            self.seconds = not self.seconds
        elif command == "reset_range":
            self.range = self.source_bounds
            self.cursor = self.source_bounds[1]
            self.follow = True
            self.interval_start = None
            self.request_key = None
        elif command == "use_interval":
            if self.interval_start is not None and self.cursor is not None:
                self.range = tuple(sorted((self.interval_start, self.cursor)))
                self.follow = False
                self.request_key = None
        elif command == "follow":
            self.follow = True
            self.cursor = None
            self.request_key = None
        elif command == "network":
            self.view = "inspector"
            self.inspector.reset()
            if self.archive_active or not self.follow:
                self.inspector.mode = "genetic"
        elif command == "gene_next":
            if self.tree:
                self.tree.more(self.tree.last_parent)
                self.genealogy = self.tree.rows()
        elif command == "gene_roots":
            self.tree_root = None
            self.genealogy_key = None
        elif command == "gene_branch":
            self.tree_root = self.selected
            self.genealogy_key = None
        elif command == "intervention":
            self.intervention_index += 1
            self.payload_scroll = 0
        elif command == "generation_more":
            self.generation_offset += 8
        elif command == "intervention_page" and self.data:
            source = self.source()
            page = self.data["interventions"]
            last = page[-1] if page else {"tick": -1, "id": ""}
            next_page = source.interventions(
                self.range[0],
                min(self.range[1], self.cursor),
                after_tick=last["tick"],
                after_id=last["id"],
            )
            self.data["interventions"] = next_page or source.interventions(
                self.range[0], min(self.range[1], self.cursor)
            )
            self.intervention_index, self.payload_scroll = 0, 0
        elif self.archive_active or self.browser_only:
            if command == "inspector":
                self.view = "inspector"
            elif command.startswith("inspect_") and command != "inspect_capture":
                super()._command(command)
            else:
                self.message = (
                    "Archivio in sola lettura; usa Corrente per i controlli della simulazione"
                )
        else:
            if command == "inspect_live":
                self.follow = True
                self.cursor = None
            previous = id(self.simulation)
            super()._command(command)
            if id(self.simulation) != previous:
                self.reset_source()

    def button(self, key, label, rect, active=False):
        self.buttons[key] = rect
        pygame.draw.rect(
            self.screen, (41, 91, 89) if active else (39, 50, 65), rect, border_radius=4
        )
        self._text(label, rect.x + 6, rect.y + 6, small=True)

    def extensions(self):
        width = self.screen.get_width()
        self.button(
            "dashboard", "Dashboard", pygame.Rect(1004, 36, 100, 29), self.view == "dashboard"
        )
        self.button("current", "Corrente", pygame.Rect(1110, 36, 90, 29), not self.archive_active)
        self.path_rect = pygame.Rect(452, 73, max(120, width - 588), 28)
        pygame.draw.rect(
            self.screen, (44, 65, 79) if self.path_active else (28, 38, 51), self.path_rect
        )
        self.screen.set_clip(self.path_rect)
        self._text(self.archive_path or "Percorso SQLite", self.path_rect.x + 6, 80, small=True)
        self.screen.set_clip(None)
        self.button("database", "Apri SQLite", pygame.Rect(width - 128, 73, 112, 28))
        if self.message:
            self.screen.set_clip(pygame.Rect(410, 109, width - 420, 28))
            self._text(self.message, 415, 117, (240, 196, 126), small=True)
            self.screen.set_clip(None)

    def chrome(self):
        self.screen.fill((15, 21, 30))
        self.buttons = {}
        self._text("Digital Life Lab", 14, 10)
        status = (
            "ARCHIVIO | sola lettura"
            if self.archive_active or self.browser_only
            else (
                f"tick {self.simulation.tick} | seed {self.simulation.seed} | "
                f"vel. effettiva {self.actual_speed:.1f}x"
            )
        )
        self._text(status, 180, 10)
        labels = [
            ("play", "Play" if self.paused else "Pausa"),
            ("tick", "Tick"),
            ("speed", f"Vel. {self.speed}x"),
            ("sensors", "Sensori"),
            ("signals", "Segnali"),
            ("energy", "Energia"),
            ("trails", "Tracce"),
            ("export", "Esporta CSV"),
            ("world", "Mondo"),
            ("inspector", "Rete"),
        ]
        x = 14
        for key, label in labels:
            size = 118 if key == "export" else 90
            self.button(key, label, pygame.Rect(x, 36, size, 29))
            x += size + 6
        self.seed_rect = pygame.Rect(62, 73, 150, 28)
        self._text("Seed:", 14, 79)
        pygame.draw.rect(self.screen, (28, 38, 51), self.seed_rect)
        self._text(self.seed_text, 68, 79)
        self.button("new", "Nuovo esperimento", pygame.Rect(222, 73, 178, 28))
        self.button("save", "Salva .dlcp", pygame.Rect(14, 109, 112, 28))
        self.button("load", "Carica", pygame.Rect(134, 109, 82, 28))
        self.button("recent", "Recenti", pygame.Rect(224, 109, 82, 28))
        self.checkpoint_rect = pygame.Rect(316, 109, max(100, self.screen.get_width() - 335), 28)
        pygame.draw.rect(self.screen, (28, 38, 51), self.checkpoint_rect)
        self.screen.set_clip(self.checkpoint_rect)
        self._text(self.checkpoint_text or "Percorso .dlcp", 322, 116, small=True)
        self.screen.set_clip(None)

    def draw_library(self):
        self._text("Esperimenti salvati — seleziona una riga", 16, 155)
        self.button("experiments_next", "Pagina successiva / prima", pygame.Rect(850, 150, 215, 28))
        y = 196
        capacity = max(1, (self.screen.get_height() - 220) // 34)
        for row in self.library_rows[self.library_scroll : self.library_scroll + capacity]:
            key = "experiment:" + row["id"]
            self.button(
                key,
                f"{row['id']} | seed {row['seed']} | {row['status']} | {row['started_at']}",
                pygame.Rect(16, y, self.screen.get_width() - 32, 29),
            )
            y += 34
        if not self.library_rows:
            self._text("Nessun esperimento disponibile", 16, 202)

    def update_request(self, source):
        result = self.worker.poll()
        if result:
            data, error = result
            if error:
                self.message = error
            else:
                self.data = data
        now = time.perf_counter()
        if now - self.request_time < 0.2 and self.request_key is not None:
            return
        self.request_time = now
        low, high = sample_bounds(source)
        if low is None:
            return
        self.source_bounds = (low, high)
        if self.range is None:
            self.range = (max(low, high - 30000), high)
        if self.follow:
            span = self.range[1] - self.range[0]
            self.range = (max(low, high - max(1, span)), high)
            self.cursor = high
        self.cursor = min(high, max(low, self.cursor if self.cursor is not None else high))
        start, end = self.range
        if self.group == "Genealogia":
            return
        cutoff = high
        overlay = ()
        if not self.archive_active:
            head = source.connection.execute(
                "SELECT tick FROM experiment_heads WHERE experiment_id=?", (source.experiment_id,)
            ).fetchone()
            cutoff = head[0] if head else high
            overlay = tuple(source.samples(after=cutoff, limit=2000))
        key = (
            str(source.database),
            source.experiment_id,
            self.group,
            start,
            end,
            cutoff,
            self.cursor,
            high,
            self.screen.get_size(),
        )
        if key != self.request_key:
            self.request_key = key
            self.worker.request(
                DataRequest(
                    str(source.database),
                    source.experiment_id,
                    self.group,
                    start,
                    end,
                    cutoff,
                    self.cursor,
                    min(700, self.screen.get_width() // 2),
                    overlay,
                )
            )

    def tick_at(self, x, rect):
        start, end = self.range
        return round(start + min(1, max(0, (x - rect.x) / max(1, rect.width))) * (end - start))

    def plot(self, title, keys, rect):
        pygame.draw.rect(self.screen, (22, 32, 44), rect, border_radius=5)
        self._text(title, rect.x + 10, rect.y + 9)
        area = pygame.Rect(
            rect.x + 58, rect.y + 59, max(40, rect.width - 78), max(40, rect.height - 96)
        )
        self.plots.append(area)
        points = self.data["points"]
        values = [
            p[k] for p in points for k in keys if k not in self.hidden and p.get(k) is not None
        ]
        low, high = (min(values), max(values)) if values else (0, 1)
        low = min(0, low)
        high = high if high > low else low + 1
        start, end = self.range
        for j in range(4):
            sy = area.bottom - j * area.height / 3
            pygame.draw.line(self.screen, (39, 53, 67), (area.x, sy), (area.right, sy))
            self._text(f"{low + (high - low) * j / 3:.3g}", rect.x + 4, sy - 5, small=True)
        for index, key in enumerate(keys):
            color = COLORS[index % len(COLORS)]
            legend = pygame.Rect(
                rect.x + 10 + index * max(100, (rect.width - 20) // len(keys)),
                rect.y + 32,
                max(90, (rect.width - 20) // len(keys)),
                20,
            )
            self.legends.append((legend, key))
            self.screen.set_clip(legend)
            self._text(
                LABELS.get(key, key),
                legend.x,
                legend.y,
                (100, 110, 125) if key in self.hidden else color,
                small=True,
            )
            self.screen.set_clip(None)
            if key in self.hidden:
                continue
            previous = None
            previous_segment = None
            for point in points:
                value = point.get(key)
                if value is None:
                    previous = None
                    continue
                position = (
                    round(area.x + (point["tick"] - start) / max(1, end - start) * area.width),
                    round(area.bottom - (value - low) / (high - low) * area.height),
                )
                if not (
                    area.left <= position[0] <= area.right
                    and area.top <= position[1] <= area.bottom
                ):
                    continue
                if previous is not None and previous_segment == point.get("segment", 0):
                    # Retained extrema are actual samples. Original source gaps are
                    # represented separately below, never inferred from decimated spacing.
                    pygame.draw.line(self.screen, color, previous, position, 2)
                pygame.draw.circle(self.screen, color, position, 2)
                previous = position
                previous_segment = point.get("segment", 0)
        if self.cursor is not None:
            px = area.x + (self.cursor - start) / max(1, end - start) * area.width
            if area.x <= px <= area.right:
                pygame.draw.line(self.screen, (223, 226, 181), (px, area.y), (px, area.bottom), 1)
        for entry in self.data["interventions"]:
            px = area.x + (entry["tick"] - start) / max(1, end - start) * area.width
            if area.x <= px <= area.right:
                pygame.draw.line(self.screen, (195, 151, 226), (px, area.y), (px, area.bottom), 1)
        if self.interval_start is not None:
            a, b = sorted((self.interval_start, self.cursor))
            overlay = pygame.Surface(area.size, pygame.SRCALPHA)
            x1 = (a - start) / max(1, end - start) * area.width
            x2 = (b - start) / max(1, end - start) * area.width
            pygame.draw.rect(overlay, (120, 170, 210, 35), (x1, 0, max(1, x2 - x1), area.height))
            self.screen.blit(overlay, area)
        factor = self.data["dt"] if self.seconds else 1
        suffix = "s" if self.seconds else "tick"
        self._text(f"{start * factor:.4g} {suffix}", area.x, area.bottom + 10, small=True)
        self._text(f"{end * factor:.4g} {suffix}", area.right - 95, area.bottom + 10, small=True)
        if not values:
            self._text("Dati non registrati nell'intervallo", area.x + 10, area.centery, small=True)

    def draw_details(self, rect):
        source = self.source()
        keys = tuple(dict.fromkeys(k for _, series in GROUPS[self.group] for k in series))
        sample, values = (
            sample_values(source, self.cursor, keys) if self.cursor is not None else (None, {})
        )
        x, y = rect.x, rect.y
        self._text("Cursore e dati originali", x, y)
        y += 27
        if sample:
            self._text(f"Campione effettivo: tick {sample['tick']}", x, y, small=True)
            y += 21
            for key in () if self.group == "Longevita" else keys:
                value = values[key]
                label = LABELS.get(key, key)
                formatted = "non registrato" if value is None else f"{value:.8g}"
                self._text(f"{label}: {formatted}", x, y, small=True)
                y += 19
            if sample["population"] == 0:
                self._text(
                    "Popolazione assente: medie strutturali non applicabili", x, y, small=True
                )
                y += 23
        if self.group == "Popolazione":
            self._text("Generazioni nel campione", x, y)
            y += 25
            distribution = (
                json.loads(sample.get("generation_distribution") or "{}") if sample else {}
            )
            items = sorted(distribution.items(), key=lambda item: int(item[0]))
            if self.generation_offset >= len(items):
                self.generation_offset = 0
            if len(items) > 8:
                self.button(
                    "generation_more", "Generazioni: successive", pygame.Rect(x, y, 240, 25)
                )
                y += 32
            for gen, count in items[self.generation_offset : self.generation_offset + 8]:
                self._text(f"Generazione {gen}: {count}", x, y, small=True)
                y += 19
        if self.group == "Eventi":
            self._text("Cause di morte registrate", x, y)
            y += 26
            causes = json.loads(sample.get("death_causes") or "{}") if sample else {}
            for cause, count in causes.items():
                self._text(f"{cause}: {count}", x, y, small=True)
                y += 20
            extinction = (
                self.data["extinction_tick"]
                if self.data["request"].cursor == self.cursor
                else "aggiornamento"
            )
            self._text(f"Estinzione osservata: {extinction}", x, y, small=True)
            y += 22
            self._text("Nessuna diagnosi ecologica automatica", x, y, small=True)
        if self.group == "Diversita" and sample:
            self._text(
                f"Coppie deterministiche: {sample.get('diversity_pairs', 'N/D')}", x, y, small=True
            )
            y += 23
            self._text("Misura descrittiva approssimata", x, y, small=True)
        life = self.data.get("life") if self.data["request"].cursor == self.cursor else None
        if life:
            for label, key in (
                ("Vite concluse", "completed"),
                ("Media vite concluse (s)", "mean"),
                ("Mediana vite concluse (s)", "median"),
                ("Vivi: durate censurate", "living_censored"),
                ("Eta media osservata vivi (s)", "living_mean_age"),
            ):
                value = life[key]
                self._text(
                    f"{label}: {value:.6g}" if value is not None else f"{label}: N/D",
                    x,
                    y,
                    small=True,
                )
                y += 22
            self._text(f"Dati individuali confermati al tick {life['tick']}", x, y, small=True)
            y += 25
            histogram = life["histogram"]
            if histogram:
                self._text("Distribuzione delle vite concluse", x, y, small=True)
                y += 23
                maximum = max(r["count"] for r in histogram)
                for row in histogram:
                    pygame.draw.rect(
                        self.screen,
                        COLORS[0],
                        (
                            x + row["bin"] * 22,
                            y + 65 - 60 * row["count"] / maximum,
                            18,
                            60 * row["count"] / maximum,
                        ),
                    )
                self._text(
                    f"{life['histogram_min']:.3g} - {life['histogram_max']:.3g} s",
                    x,
                    y + 75,
                    small=True,
                )
        interventions = [
            entry for entry in self.data["interventions"] if entry["tick"] <= self.cursor
        ]
        if interventions:
            entry = interventions[self.intervention_index % len(interventions)]
            self.button(
                "intervention", "Intervento: successivo", pygame.Rect(x, rect.bottom - 100, 220, 26)
            )
            self._text(
                f"tick {entry['tick']} | {entry['kind']} | {entry['label']}",
                x,
                rect.bottom - 68,
                small=True,
            )
            self.button(
                "intervention_page", "Pagina interventi", pygame.Rect(x, rect.bottom - 133, 220, 26)
            )
            payload = str(entry["payload_json"])
            offset = self.payload_scroll * 48
            for index in range(3):
                self._text(
                    payload[offset + index * 48 : offset + (index + 1) * 48],
                    x,
                    rect.bottom - 43 + index * 14,
                    small=True,
                )
            self.payload_length = len(payload)

    def draw_genealogy(self, rect):
        source = self.source()
        cursor = self.cursor if self.cursor is not None else self.source_bounds[1]
        key = (
            id(source.connection),
            source.experiment_id,
            cursor,
            self.tree_root,
            self.genealogy_lineage,
        )
        if key != self.genealogy_key:
            self.tree = GenealogyTree(source, cursor, self.genealogy_lineage, self.tree_root)
            self.genealogy = self.tree.rows()
            self.genealogy_key = key
            self.genealogy_scroll = 0
        self._text("Genealogia — seleziona un individuo; + apre i figli", rect.x, rect.y)
        self.button("gene_roots", "Fondatori", pygame.Rect(rect.x, rect.y + 30, 110, 27))
        self.button(
            "gene_next", "Pagina successiva", pygame.Rect(rect.x + 120, rect.y + 30, 150, 27)
        )
        self.button(
            "network", "Apri rete selezionata", pygame.Rect(rect.x + 280, rect.y + 30, 170, 27)
        )
        self.lineage_rect = pygame.Rect(rect.x + 470, rect.y + 30, 200, 27)
        self.button(
            "gene_branch", "Ramo selezionato", pygame.Rect(rect.x + 680, rect.y + 30, 155, 27)
        )
        pygame.draw.rect(self.screen, (38, 57, 75), self.lineage_rect, border_radius=4)
        self._text(
            self.lineage_text or "Linea ID; vuoto = tutte",
            self.lineage_rect.x + 5,
            self.lineage_rect.y + 7,
            small=True,
        )
        y = rect.y + 72
        self.genealogy_rows = []
        capacity = max(1, (rect.height - 75) // 27)
        for row in self.genealogy[self.genealogy_scroll : self.genealogy_scroll + capacity]:
            line = pygame.Rect(rect.x, y, rect.width, 25)
            pygame.draw.rect(
                self.screen, (39, 69, 79) if self.selected == row["id"] else (24, 35, 47), line
            )
            marker = "-" if row["id"] in self.tree.expanded else "+"
            indent = min(row.get("depth", 0), 12) * 15
            self._text(marker, rect.x + 7 + indent, y + 5)
            state = "morto" if row["death_tick"] is not None else "vivo al cursore"
            self._text(
                f"ID {row['id']} | genitore {row['parent_id']} | linea {row['lineage_id']} | "
                f"generazione {row['generation']} | nascita {row['born_tick']} | {state}",
                rect.x + 34 + indent,
                y + 6,
                small=True,
            )
            self.genealogy_rows.append((line, row))
            y += 27
        if not self.genealogy:
            self._text("Nessun individuo disponibile per questi filtri", rect.x, y + 5)
        if self.tree.limit_reached:
            self._text(
                "Limite di 500 nodi visibili: collassa un ramo o apri il ramo selezionato",
                rect.x,
                rect.bottom - 15,
                small=True,
            )

    def draw_dashboard(self):
        source = self.source()
        if source is None:
            self._text("Apri SQLite e seleziona un esperimento", 20, 180)
            return
        self.update_request(source)
        metadata = source.metadata()
        width, height = self.screen.get_size()
        self._text(f"{metadata['id']} | seed {metadata['seed']} | {metadata['status']}", 14, 154)
        x = 14
        for name in (*GROUPS, "Genealogia"):
            self.button("group:" + name, name, pygame.Rect(x, 181, 112, 27), name == self.group)
            x += 118
        self.button(
            "axis", "Asse: secondi" if self.seconds else "Asse: tick", pygame.Rect(14, 216, 120, 26)
        )
        self.button("reset_range", "Tutto", pygame.Rect(142, 216, 65, 26))
        self.button("follow", "Segui ultimo tick", pygame.Rect(215, 216, 125, 26), self.follow)
        self.button("network", "Apri rete", pygame.Rect(348, 216, 90, 26))
        self.button("use_interval", "Usa intervallo", pygame.Rect(446, 216, 125, 26))
        self._text(
            "Ruota: zoom | Trascina: intervallo | Tasto centrale: scorri | Click: cursore",
            580,
            224,
            small=True,
        )
        self._text(
            "Reti: struttura. Plasticita: snapshot Inspector. "
            "Adattamento comportamentale e intelligenza non valutati.",
            14,
            height - 24,
            (225, 197, 129),
            small=True,
        )
        if self.group == "Genealogia":
            self.draw_genealogy(pygame.Rect(14, 260, width - 28, height - 300))
            return
        if self.data is None or self.data["request"].group != self.group:
            self._text("Caricamento progressivo dei dati...", 20, 290)
            return
        origin = self.data["origin"]
        note = (
            f"Diramazione di {origin['parent_experiment_id']} al tick {origin['fork_tick']}; "
            "prefisso condiviso"
            if origin
            else ""
        )
        count = self.data["source_samples"]
        self._text(
            f"Intervallo {self.range} | cursore {self.cursor} | "
            f"campioni {count if count is not None else 'decessi'} | "
            f"punti {len(self.data['points'])}, estremi per pixel | {note}",
            14,
            252,
            small=True,
        )
        plots = GROUPS[self.group]
        panel_width = min(340, width // 4)
        area = pygame.Rect(14, 280, width - panel_width - 40, height - 320)
        self.plots, self.legends = [], []
        columns = 2 if len(plots) > 2 else 1
        rows = math.ceil(len(plots) / columns)
        for i, (title, series) in enumerate(plots):
            rect = pygame.Rect(
                area.x + (i % columns) * (area.width // columns + 4),
                area.y + (i // columns) * (area.height // rows + 4),
                area.width // columns - 4,
                area.height // rows - 6,
            )
            self.plot(title, series, rect)
        self.detail_rect = pygame.Rect(width - panel_width - 10, 280, panel_width, height - 320)
        self.screen.set_clip(self.detail_rect)
        self.draw_details(pygame.Rect(width - panel_width - 10, 280, panel_width, height - 320))
        self.screen.set_clip(None)
        if self.hover_tick is not None and self.hover_pos and self.group != "Longevita":
            keys = tuple(dict.fromkeys(k for _, series in GROUPS[self.group] for k in series))
            sample, values = sample_values(source, self.hover_tick, keys)
            if sample:
                tx = min(width - 360, max(10, self.hover_pos[0] + 15))
                ty = min(height - 140, max(260, self.hover_pos[1] - 95))
                pygame.draw.rect(
                    self.screen, (40, 57, 73), (tx, ty, 350, 25 + len(keys) * 18), border_radius=4
                )
                self._text(f"Dato originale: tick {sample['tick']}", tx + 7, ty + 7, small=True)
                for i, key in enumerate(keys):
                    value = values[key]
                    formatted = "non registrato" if value is None else f"{value:.8g}"
                    self._text(f"{LABELS[key]}: {formatted}", tx + 7, ty + 28 + i * 18, small=True)

    def draw(self):
        if (
            self.view in {"world", "inspector"}
            and not self.archive_active
            and not self.browser_only
        ):
            super().draw()
            self.extensions()
            pygame.display.flip()
            return
        self.chrome()
        if self.view == "library":
            self.draw_library()
        elif self.view == "inspector":
            try:
                self.inspector.draw(
                    self,
                    pygame.Rect(
                        14, 155, self.screen.get_width() - 28, self.screen.get_height() - 170
                    ),
                )
            except (ValueError, sqlite3.Error) as error:
                self._text(str(error), 20, 280)
        else:
            try:
                self.draw_dashboard()
            except (ValueError, sqlite3.Error) as error:
                self._text(str(error), 20, 280)
        self.extensions()
        pygame.display.flip()

    def dashboard_event(self, event):
        if self.view == "library" and event.type == pygame.MOUSEWHEEL:
            self.library_scroll = max(
                0, min(max(0, len(self.library_rows) - 1), self.library_scroll - event.y * 3)
            )
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.path_active = self.path_rect.collidepoint(event.pos)
            if self.path_active:
                self.seed_active = self.checkpoint_active = False
                return True
        if event.type == pygame.KEYDOWN and self.path_active:
            if event.key == pygame.K_RETURN:
                self.command("database")
                self.path_active = False
            elif event.key == pygame.K_BACKSPACE:
                self.archive_path = self.archive_path[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.archive_path += event.unicode
            return True
        if self.view != "dashboard":
            return False
        if self.group == "Genealogia":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.lineage_active = self.lineage_rect.collidepoint(event.pos)
                if self.lineage_active:
                    return True
                for rect, row in self.genealogy_rows:
                    if rect.collidepoint(event.pos):
                        self.selected = row["id"]
                        indent = min(row.get("depth", 0), 12) * 15
                        if event.pos[0] < rect.x + 30 + indent:
                            self.follow = False
                            self.tree.toggle(row["id"])
                            self.genealogy = self.tree.rows()
                        return True
            elif event.type == pygame.MOUSEWHEEL:
                self.genealogy_scroll = max(
                    0, min(max(0, len(self.genealogy) - 1), self.genealogy_scroll - event.y * 3)
                )
                return True
            elif event.type == pygame.KEYDOWN and self.lineage_active:
                if event.key == pygame.K_RETURN:
                    self.genealogy_lineage = int(self.lineage_text) if self.lineage_text else None
                    self.genealogy_key, self.genealogy_after = None, 0
                    self.lineage_active = False
                elif event.key == pygame.K_BACKSPACE:
                    self.lineage_text = self.lineage_text[:-1]
                elif event.unicode.isdecimal():
                    self.lineage_text += event.unicode
                return True
            return False
        if not self.range:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN:
            for rect, key in self.legends:
                if rect.collidepoint(event.pos):
                    self.hidden.symmetric_difference_update({key})
                    return True
            for rect in self.plots:
                if rect.collidepoint(event.pos):
                    tick = self.tick_at(event.pos[0], rect)
                    self.follow = False
                    if event.button == 1:
                        self.cursor = tick
                        self.interval_start = tick
                        self.drag_tick = (event.pos[0], tick, rect, 1)
                    elif event.button == 2:
                        self.drag_tick = (event.pos[0], self.range, rect, 2)
                    return True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.drag_tick = None
        elif event.type == pygame.MOUSEMOTION and self.drag_tick:
            x, value, rect, button = self.drag_tick
            if button == 1:
                self.cursor = self.tick_at(event.pos[0], rect)
            else:
                span = value[1] - value[0]
                shift = round((x - event.pos[0]) * span / max(1, rect.width))
                low, high = self.source_bounds
                start = min(max(low, value[0] + shift), max(low, high - span))
                self.range = (start, min(high, start + span))
            self.request_key = None
            return True
        elif event.type == pygame.MOUSEMOTION:
            self.hover_tick = None
            for rect in self.plots:
                if rect.collidepoint(event.pos):
                    self.hover_tick = self.tick_at(event.pos[0], rect)
                    self.hover_pos = event.pos
                    break
        elif event.type == pygame.MOUSEWHEEL and self.plots:
            if (
                getattr(self, "detail_rect", pygame.Rect(0, 0, 0, 0)).collidepoint(
                    pygame.mouse.get_pos()
                )
                and self.data
                and self.data["interventions"]
            ):
                self.payload_scroll = max(
                    0,
                    min(
                        max(0, getattr(self, "payload_length", 0) // 48),
                        self.payload_scroll - event.y * 3,
                    ),
                )
                return True
            rect = next((r for r in self.plots if r.collidepoint(pygame.mouse.get_pos())), None)
            if rect is None:
                return False
            anchor = self.tick_at(pygame.mouse.get_pos()[0], rect)
            low, high = self.source_bounds
            span = max(1, round((self.range[1] - self.range[0]) * 1.3 ** (-event.y)))
            start = max(low, anchor - span // 2)
            self.range = (start, min(high, start + span))
            self.follow = False
            self.request_key = None
            return True
        return False

    def run(self, on_tick=None, max_frames=None, should_stop=None):
        self.on_tick = on_tick
        frames = measured_ticks = 0
        last_measure = time.perf_counter()
        running = True
        try:
            self.draw()
            while running:
                elapsed = min(self.clock.tick(60) / 1000, 0.25)
                for event in pygame.event.get():
                    if event.type == pygame.VIDEORESIZE:
                        pygame.display.set_mode(
                            (max(1280, event.w), max(800, event.h)), pygame.RESIZABLE
                        )
                    if self.dashboard_event(event):
                        continue
                    if self.view == "inspector" and self.inspector.event(event, self):
                        continue
                    if event.type == pygame.QUIT:
                        running = not self._request_close()
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self.seed_active = self.seed_rect.collidepoint(event.pos)
                        self.checkpoint_active = self.checkpoint_rect.collidepoint(event.pos)
                        for key, rect in self.buttons.items():
                            if rect.collidepoint(event.pos):
                                self.command(key)
                                break
                        else:
                            if self.view == "world" and not self.archive_active:
                                viewport, scale, _ = self._layout()
                                if viewport.collidepoint(event.pos):
                                    point = (
                                        (event.pos[0] - viewport.x) / scale,
                                        (event.pos[1] - viewport.y) / scale,
                                    )
                                    closest = min(
                                        (
                                            (math.dist(o.position, point), i)
                                            for i, o in self.simulation.world.organisms.items()
                                        ),
                                        default=(math.inf, None),
                                    )
                                    if closest[0] < max(12, 10 / scale):
                                        self.selected = closest[1]
                    elif event.type == pygame.KEYDOWN:
                        if self.checkpoint_active:
                            if event.key == pygame.K_BACKSPACE:
                                self.checkpoint_text = self.checkpoint_text[:-1]
                            elif event.key == pygame.K_RETURN:
                                self.command("load")
                                self.checkpoint_active = False
                            elif event.unicode and event.unicode.isprintable():
                                self.checkpoint_text += event.unicode
                        elif self.seed_active:
                            if event.key == pygame.K_BACKSPACE:
                                self.seed_text = self.seed_text[:-1]
                            elif event.key == pygame.K_RETURN:
                                self.command("new")
                                self.seed_active = False
                            elif event.unicode.isdecimal() and len(self.seed_text) < 18:
                                self.seed_text += event.unicode
                        elif event.key == pygame.K_SPACE:
                            self.command("play")
                        elif event.key == pygame.K_PERIOD:
                            self.command("tick")
                        elif event.key == pygame.K_ESCAPE:
                            running = not self._request_close()
                if (
                    not self.paused
                    and running
                    and not self.archive_active
                    and not self.browser_only
                ):
                    dt = self.simulation.config.world.dt
                    self.accumulator = min(self.accumulator + elapsed * self.speed, dt * 256)
                    started = time.perf_counter()
                    while self.accumulator >= dt:
                        if should_stop and should_stop():
                            break
                        self.simulation.step()
                        measured_ticks += 1
                        self.accumulator -= dt
                        if not self._observe_tick() or time.perf_counter() - started > 0.025:
                            break
                now = time.perf_counter()
                if now - last_measure >= 0.5:
                    self.actual_speed = (
                        measured_ticks * self.simulation.config.world.dt / (now - last_measure)
                    )
                    measured_ticks, last_measure = 0, now
                self.draw()
                frames += 1
                if (max_frames is not None and frames >= max_frames) or (
                    should_stop and should_stop()
                ):
                    if not self._request_close():
                        raise RuntimeError(self.message)
                    running = False
        finally:
            self.worker.close()
            if self.archive_reader:
                self.archive_reader.close()
            if self.library:
                self.library.close()
            pygame.quit()
