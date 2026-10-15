"""Pygame neural observation panel. Layout and filtering never enter the engine."""

import math

import numpy as np
import pygame

from .brain import OUTPUT_NAMES
from .neural_layout import graph_layout
from .observations import NeuralSnapshot, capture_neural, genetic_difference
from .sensors import SENSOR_NAMES


def _color(value, scale=1):
    intensity = min(1, abs(value) / max(scale, 1e-12))
    return (
        (round(65 + 180 * intensity), 100, 118)
        if value < 0
        else (65, round(95 + 140 * intensity), round(115 + 110 * intensity))
    )


class InspectorPanel:
    def __init__(self):
        self.mode = "live"
        self.snapshot_tick = None
        self.ancestor_id = None
        self.search = ""
        self.search_active = False
        self.zoom = 1.0
        self.pan = (0, 0)
        self.node = None
        self.edge = None
        self.filter = "all"
        self.offset = 0
        self.graph_rects = []
        self.points = {}
        self.cached_key = None
        self.cached_data = None
        self.layouts = {}
        self.edge_surfaces = {}
        self.labels = {}
        self.birth_genome = None
        self.drag = None
        self.last_identifier = None
        self.availability = ""

    def reset(self):
        self.__init__()

    def sync_selection(self, identifier):
        if self.last_identifier is not None and self.last_identifier != identifier:
            self.mode, self.snapshot_tick, self.ancestor_id = "live", None, None
            self.node, self.edge, self.offset = None, None, 0
        self.last_identifier = identifier

    def button(self, renderer, key, label, x, y, width):
        rect = pygame.Rect(x, y, width, 27)
        renderer.buttons["inspect_" + key] = rect
        pygame.draw.rect(renderer.screen, (38, 57, 75), rect, border_radius=4)
        renderer._text(label, x + 6, y + 6, small=True)

    def command(self, key, renderer):
        self.sync_selection(renderer.selected)
        reader = renderer.on_reader() if renderer.on_reader else None
        identifier = renderer.selected
        if key in {"live", "genetic"}:
            self.mode = key
        elif key == "capture":
            if renderer.observation_pending:
                raise ValueError("Recuperare prima le osservazioni pendenti con Play/Tick")
            if renderer.on_capture is None:
                raise ValueError("Persistenza non disponibile in questa sessione")
            snapshot = renderer.on_capture(identifier)
            renderer.message = f"Snapshot persistente: organismo {identifier}, tick {snapshot.tick}"
        elif key == "snapshot":
            if reader is None or identifier is None:
                raise ValueError("Nessuno storico disponibile")
            rows = reader.snapshots(
                identifier, after=self.snapshot_tick if self.snapshot_tick is not None else -1
            )
            if not rows:
                rows = reader.snapshots(identifier)
            if not rows:
                raise ValueError("Attivazioni e plasticita storiche non registrate")
            self.snapshot_tick = rows[0]["tick"]
            self.mode = "snapshot"
        elif key == "ancestor":
            if reader is None:
                raise ValueError("Archivio degli antenati non disponibile")
            row = reader.individual(
                self.ancestor_id if self.ancestor_id is not None else identifier
            )
            if row is None and renderer.simulation and not renderer.archive_active:
                row = renderer.simulation.records.get(
                    self.ancestor_id if self.ancestor_id is not None else identifier
                )
            self.ancestor_id = row["parent_id"] if row else None
            if self.ancestor_id is None:
                renderer.message = "Nessun altro antenato; confronto disattivato"
        elif key == "clear":
            self.ancestor_id = None
        elif key == "filter":
            filters = ["all", "plastic", "incident", "input", "hidden", "output"]
            self.filter = filters[(filters.index(self.filter) + 1) % len(filters)]
            self.offset = 0
        elif key in {"up", "down"}:
            self.offset = max(0, self.offset + (-10 if key == "up" else 10))
        elif key == "fit":
            self.zoom, self.pan = 1, (0, 0)
        self.cached_key = None

    def _data(self, renderer, reader):
        identifier = renderer.selected
        simulation = renderer.simulation
        key = (
            id(simulation),
            simulation.tick if simulation else -1,
            identifier,
            self.mode,
            self.snapshot_tick,
            id(reader.connection) if reader else None,
            getattr(reader, "cursor", None),
        )
        if key == self.cached_key:
            return self.cached_data
        data = None
        if (
            self.mode in {"live", "genetic"}
            and simulation is not None
            and not renderer.archive_active
            and identifier in simulation.world.organisms
        ):
            organism_genome = simulation.world.organisms[identifier].genome
            genetic = (
                self.birth_genome[1:]
                if self.birth_genome and self.birth_genome[0] is organism_genome
                else None
            )
            data = capture_neural(
                simulation,
                identifier,
                reader.experiment_id if reader else "current",
                _genetic=genetic,
            )
            self.birth_genome = (organism_genome, data.genome_id, data.genome)
            if self.mode == "genetic":
                data = NeuralSnapshot(
                    data.experiment_id, data.organism_id, -1, data.genome_id, data.genome
                )
        elif reader and identifier is not None:
            data = (
                reader.snapshot(identifier, self.snapshot_tick)
                if self.mode == "snapshot" and self.snapshot_tick is not None
                else reader.genome(identifier)
            )
        self.cached_key, self.cached_data = key, data
        return data

    def draw_graph(self, renderer, data, rect, bound, *, comparison=None, interactive=True):
        screen = renderer.screen
        pygame.draw.rect(screen, (19, 29, 40), rect, border_radius=5)
        positions = self.layouts.get(data.genome_id)
        if positions is None:
            positions = graph_layout(data.genome)
            if len(self.layouts) >= 16:
                self.layouts.clear()
            self.layouts[data.genome_id] = positions
        points = {
            i: (
                round(rect.centerx + (p[0] - 0.5) * rect.width * self.zoom + self.pan[0]),
                round(rect.centery + (p[1] - 0.5) * rect.height * self.zoom + self.pan[1]),
            )
            for i, p in positions.items()
        }
        inherited, effective = data.weights(bound)
        display_weights = effective if effective is not None else inherited
        node_values = dict(zip(sorted(points), data.activities or (), strict=False))
        screen.set_clip(rect)
        added = (
            (set(comparison["edges_added"]) | set(comparison["weights_changed"]))
            if comparison
            else set()
        )
        # Cache rendered pixels only. Numeric values and the edge table retain
        # their full precision; every frame checks all current display styles.
        intensity = np.minimum(1, np.abs(display_weights) / max(bound, 1e-12))
        colors = np.empty((len(display_weights), 3), dtype=np.uint8)
        negative = display_weights < 0
        colors[:, 0] = np.where(negative, np.rint(65 + 180 * intensity), 65)
        colors[:, 1] = np.where(negative, 100, np.rint(95 + 140 * intensity))
        colors[:, 2] = np.where(negative, 118, np.rint(115 + 110 * intensity))
        widths = (1 + (np.abs(display_weights) / bound * 2).astype(int)).tolist()
        visible = range(len(display_weights))
        if self.filter == "plastic":
            visible = (
                np.flatnonzero(np.abs(data.acquired) > 1e-12).tolist()
                if data.acquired is not None
                else []
            )
        elif self.filter == "incident":
            visible = [
                i for i, (a, b, _) in enumerate(data.genome["connections"]) if self.node in (a, b)
            ]
        if added:
            for index, (source, target, _) in enumerate(data.genome["connections"]):
                if (source, target) in added:
                    colors[index] = (242, 195, 72)
        if interactive and self.edge is not None and self.edge < len(widths):
            widths[self.edge] = 3
        style = (
            data.genome_id,
            tuple(rect),
            self.zoom,
            self.pan,
            self.filter,
            self.node,
            self.edge if interactive else None,
            tuple(visible),
            tuple(widths),
        )
        cached = self.edge_surfaces.get(interactive)
        rebuild = cached is None or cached[0] != style
        if rebuild:
            edges = pygame.Surface(rect.size).convert()
            edges.fill((19, 29, 40))
            changed = visible
        else:
            edges = cached[2]
            recolored = np.any(colors != cached[1], axis=1)
            changed = [i for i in visible if recolored[i]]
        if changed:
            edge_colors = colors.tolist()
            edges.lock()
            try:
                for index in changed:
                    source, target, _ = data.genome["connections"][index]
                    a = (points[source][0] - rect.x, points[source][1] - rect.y)
                    b = (points[target][0] - rect.x, points[target][1] - rect.y)
                    pygame.draw.line(edges, edge_colors[index], a, b, widths[index])
                    # Layers run left to right. Add a direction marker on focused
                    # edges so dense graphs remain readable without hiding edges.
                    if interactive and (self.edge == index or self.node in (source, target)):
                        angle = math.atan2(b[1] - a[1], b[0] - a[0])
                        tip = (a[0] + 0.8 * (b[0] - a[0]), a[1] + 0.8 * (b[1] - a[1]))
                        pygame.draw.line(
                            edges,
                            edge_colors[index],
                            tip,
                            (
                                tip[0] - 5 * math.cos(angle - 0.5),
                                tip[1] - 5 * math.sin(angle - 0.5),
                            ),
                        )
            finally:
                edges.unlock()
        # Recolor paths whose width and geometry are identical in place. Recently
        # recolored paths are drawn in front at crossings, just as focused edges
        # are; no numeric connection or table value is omitted.
        self.edge_surfaces[interactive] = (style, colors, edges)
        screen.blit(edges, rect)
        for identifier, kind, _ in data.genome["nodes"]:
            if self.filter in {"input", "hidden", "output"} and kind != self.filter:
                continue
            point = points[identifier]
            color = _color(node_values[identifier]) if identifier in node_values else (96, 110, 128)
            pygame.draw.circle(screen, color, point, 9)
            changed_node = comparison and (
                identifier in comparison["nodes_added"] or identifier in comparison["bias_changed"]
            )
            pygame.draw.circle(
                screen,
                (244, 212, 113) if identifier == self.node or changed_node else (192, 211, 228),
                point,
                10,
                2 if identifier == self.node else 1,
            )
            name = (
                SENSOR_NAMES[identifier]
                if kind == "input"
                else OUTPUT_NAMES[identifier - 16]
                if kind == "output"
                else f"h{identifier}"
            )
            label = f"{identifier} {name}"
            cache_key = (id(renderer.small), label)
            text_surface = self.labels.get(cache_key)
            if text_surface is None:
                text_surface = renderer.small.render(label, True, (220, 232, 240))
                if len(self.labels) >= 512:
                    self.labels.clear()
                self.labels[cache_key] = text_surface
            text_width = text_surface.get_width()
            label_x = point[0] - text_width - 13 if kind == "output" else point[0] + 13
            pygame.draw.rect(screen, (19, 29, 40), (label_x - 2, point[1] - 6, text_width + 4, 14))
            screen.blit(text_surface, (label_x, point[1] - 5))
        screen.set_clip(None)
        if interactive:
            self.points = points
            self.graph_rects = [rect]

    def draw(self, renderer, rect):
        reader = renderer.on_reader() if renderer.on_reader else None
        if renderer.selected is None and renderer.simulation and not renderer.archive_active:
            renderer.selected = next(iter(renderer.simulation.world.organisms), None)
        self.sync_selection(renderer.selected)
        x, y = rect.x, rect.y
        renderer._text("Neural Inspector", x, y)
        self.search_rect = pygame.Rect(x + 180, y - 3, 110, 27)
        pygame.draw.rect(renderer.screen, (38, 57, 75), self.search_rect, border_radius=4)
        renderer._text(self.search or "ID + Invio", x + 186, y + 3, small=True)
        labels = [
            ("live", "Live", 55),
            ("genetic", "Genoma", 75),
            ("capture", "Acquisisci snapshot", 150),
            ("snapshot", "Storico: successivo", 150),
            ("ancestor", "Antenato: successivo", 158),
            ("clear", "Confronto off", 110),
        ]
        bx = x
        for key, label, width in labels:
            self.button(renderer, key, label, bx, y + 30, width)
            bx += width + 5
        self.button(renderer, "filter", f"Filtro: {self.filter}", x, y + 62, 160)
        self.button(renderer, "fit", "Adatta", x + 165, y + 62, 70)
        self.button(renderer, "up", "Righe -10", x + 240, y + 62, 90)
        self.button(renderer, "down", "Righe +10", x + 335, y + 62, 90)
        renderer._text(
            "Ciano: peso + | Rosa: peso - | Giallo: differenza genetica | "
            "Ruota: zoom; trascina con tasto centrale",
            x + 440,
            y + 70,
            small=True,
        )
        data = self._data(renderer, reader)
        if data is None:
            renderer._text("Genoma non disponibile. Seleziona un ID registrato.", x, y + 110)
            renderer._text(
                "Dati neurali dinamici non registrati; non vengono ricostruiti.", x, y + 138
            )
            return
        metadata = reader.metadata() if reader else None
        bound = (
            json_config_bound(metadata)
            if metadata
            else renderer.simulation.config.neural.parameter_bound
        )
        recorded = bool(reader and reader.snapshots(data.organism_id, limit=1))
        status = (
            "genoma alla nascita; storico dinamico DISPONIBILE: usa Storico"
            if recorded
            else "genoma alla nascita; storico dinamico NON REGISTRATO"
        )
        self.availability = status
        if data.activities is not None:
            source = "SNAPSHOT REGISTRATO" if self.mode == "snapshot" else "LIVE"
            status = f"{source}, tick {data.tick} | " + (
                "inferenza non ancora eseguita"
                if data.phase == "not_evaluated"
                else "attivazioni ultima inferenza; delta DOPO apprendimento"
            )
        renderer._text(
            f"ID {data.organism_id} | {len(data.genome['nodes'])} neuroni | "
            f"{len(data.genome['connections'])} connessioni | {status}",
            x,
            y + 99,
            small=True,
        )
        renderer._text(
            "Struttura e plasticita sono distinte; "
            "adattamento vantaggioso e intelligenza non valutati.",
            x,
            y + 120,
            (229, 199, 127),
            small=True,
        )
        ancestor = reader.genome(self.ancestor_id) if reader and self.ancestor_id else None
        difference = genetic_difference(data, ancestor) if ancestor else None
        graph_height = max(150, int((rect.height - 180) * 0.66))
        graph = pygame.Rect(x, y + 147, rect.width, graph_height)
        if ancestor:
            graph.width = (rect.width - 12) // 2
        self.draw_graph(renderer, data, graph, bound, comparison=difference)
        if ancestor:
            other = graph.move(graph.width + 12, 0)
            self.draw_graph(
                renderer,
                ancestor,
                other,
                bound,
                comparison=genetic_difference(ancestor, data),
                interactive=False,
            )
            history = (
                "snapshot disponibili"
                if reader.snapshots(ancestor.organism_id, limit=1)
                else "stato dinamico non registrato"
            )
            renderer._text(
                f"Antenato {ancestor.organism_id}: genoma; {history}",
                other.x + 5,
                other.y + 5,
                small=True,
            )
        elif self.ancestor_id:
            renderer._text(
                "Genoma dell'antenato non disponibile", graph.x + 5, graph.y + 5, small=True
            )
        ty = graph.bottom + 8
        if difference:
            renderer._text(
                f"Differenze genetiche: neuroni +{len(difference['nodes_added'])}"
                f"/-{len(difference['nodes_removed'])}; connessioni "
                f"+{len(difference['edges_added'])}/-{len(difference['edges_removed'])}; "
                f"pesi {len(difference['weights_changed'])}; "
                f"bias {len(difference['bias_changed'])}",
                x,
                ty,
                small=True,
            )
            ty += 21
        if self.node is not None:
            nodes = {n[0]: n for n in data.genome["nodes"]}
            if self.node in nodes:
                index = sorted(nodes).index(self.node)
                activity = (
                    "non registrata"
                    if data.activities is None
                    else f"{data.activities[index]:+.8g}"
                )
                renderer._text(
                    f"Neurone {self.node}: {nodes[self.node][1]} | bias genetico "
                    f"{nodes[self.node][2]:+.8g} | attivazione {activity}",
                    x,
                    ty,
                    small=True,
                )
                ty += 20
        renderer._text(
            "Connessione | genetico | delta acquisito | "
            "effettivo prossimo forward | variazione effettiva",
            x,
            ty,
            small=True,
        )
        inherited, effective = data.weights(bound)
        rows = []
        ancestor_weights = (
            {(a, b): w for a, b, w in ancestor.genome["connections"]} if ancestor else {}
        )
        for i, (source, target, weight) in enumerate(data.genome["connections"]):
            if self.filter == "plastic" and (
                data.acquired is None or abs(data.acquired[i]) <= 1e-12
            ):
                continue
            if self.filter == "incident" and self.node not in (source, target):
                continue
            rows.append((i, source, target, weight))
        self.offset = min(self.offset, max(0, len(rows) - 1))
        ty += 21
        self.table_rect = pygame.Rect(x, ty, rect.width, max(0, rect.bottom - ty))
        self.table_rows = rows[self.offset : self.offset + max(0, (rect.bottom - ty) // 19)]
        for index, source, target, weight in self.table_rows:
            details = "non registrato | non registrato | non registrata"
            if effective is not None:
                saturated = (
                    " SATURAZIONE" if abs(inherited[index] + data.acquired[index]) > bound else ""
                )
                details = (
                    f"{data.acquired[index]:+.8f} | {effective[index]:+.8f} | "
                    f"{effective[index] - weight:+.8f}{saturated}"
                )
            if ancestor:
                old = ancestor_weights.get((source, target))
                details += (
                    f" | delta genetico vs antenato: {weight - old:+.8f}"
                    if old is not None
                    else " | nuova connessione genetica"
                )
            renderer._text(
                f"{source:3} -> {target:3} | {weight:+.8f} | {details}",
                x + 5,
                ty,
                (243, 208, 115) if self.edge == index else (213, 222, 232),
                small=True,
            )
            ty += 19

    def event(self, event, renderer):
        if event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1:
                self.search_active = getattr(
                    self, "search_rect", pygame.Rect(0, 0, 0, 0)
                ).collidepoint(event.pos)
                if self.search_active:
                    return True
                for identifier, point in self.points.items():
                    if math.dist(point, event.pos) < 12:
                        self.node = identifier
                        return True
                if getattr(self, "table_rect", pygame.Rect(0, 0, 0, 0)).collidepoint(event.pos):
                    index = (event.pos[1] - self.table_rect.y) // 19
                    if index < len(self.table_rows):
                        self.edge = self.table_rows[index][0]
                        return True
            if event.button == 2:
                self.drag = event.pos
                return True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 2:
            self.drag = None
        elif event.type == pygame.MOUSEMOTION and self.drag is not None:
            self.pan = (self.pan[0] + event.rel[0], self.pan[1] + event.rel[1])
            return True
        elif event.type == pygame.MOUSEWHEEL:
            if any(r.collidepoint(pygame.mouse.get_pos()) for r in self.graph_rects):
                self.zoom = min(5, max(0.3, self.zoom * 1.15**event.y))
            else:
                self.offset = max(0, self.offset - event.y * 3)
            return True
        elif event.type == pygame.KEYDOWN and self.search_active:
            if event.key == pygame.K_RETURN:
                if self.search.isdigit():
                    renderer.selected = int(self.search)
                    self.mode, self.ancestor_id, self.snapshot_tick = "live", None, None
                    self.node, self.edge, self.offset = None, None, 0
                    self.cached_key = None
                self.search_active = False
            elif event.key == pygame.K_BACKSPACE:
                self.search = self.search[:-1]
            elif event.unicode.isdecimal() and len(self.search) < 18:
                self.search += event.unicode
            return True
        return False


def json_config_bound(metadata):
    import json

    return json.loads(metadata["config_json"])["neural"]["parameter_bound"]
