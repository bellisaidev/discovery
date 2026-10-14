"""Pygame view/controller. Imported only by the graphical CLI path."""

import math
import time
from collections import deque

import numpy as np
import pygame

from .brain import OUTPUT_NAMES
from .sensors import SENSOR_NAMES


class Renderer:
    def __init__(
        self,
        simulation,
        on_new=None,
        on_export=None,
        on_save=None,
        on_load=None,
        on_list=None,
        on_close=None,
    ):
        pygame.init()
        self.screen = pygame.display.set_mode((1380, 820), pygame.RESIZABLE)
        pygame.display.set_caption("Digital Life Lab — V1")
        self.font = pygame.font.Font(None, 22)
        self.small = pygame.font.Font(None, 18)
        self.title = pygame.font.Font(None, 30)
        self.simulation = simulation
        self.on_new, self.on_export = on_new, on_export
        self.on_save, self.on_load, self.on_list, self.on_close = (
            on_save,
            on_load,
            on_list,
            on_close,
        )
        self.checkpoint_text = ""
        self.checkpoint_active = False
        self.recent_index = -1
        self.on_tick = None
        self.observation_pending = False
        self.paused = False
        self.speed = 1
        self.selected = None
        self.show_sensors = False
        self.show_signals = True
        self.show_energy = True
        self.show_trails = False
        self.seed_text = str(simulation.seed)
        self.seed_active = False
        self.message = ""
        self.trails = {}
        self.buttons = {}
        self.clock = pygame.time.Clock()
        self.accumulator = 0.0
        self.actual_speed = 0.0

    def _text(self, text, x, y, color=(213, 222, 232), small=False):
        font = self.small if small else self.font
        self.screen.blit(font.render(str(text), True, color), (x, y))

    def _layout(self):
        width, height = self.screen.get_size()
        panel_width = min(380, max(300, width // 3))
        area = pygame.Rect(12, 150, max(100, width - panel_width - 32), max(100, height - 170))
        w = self.simulation.config.world
        scale = min(area.width / w.width, area.height / w.height)
        viewport = pygame.Rect(area.x, area.y, round(w.width * scale), round(w.height * scale))
        return viewport, scale, width - panel_width

    def _point(self, position, viewport, scale):
        return (round(viewport.x + position[0] * scale), round(viewport.y + position[1] * scale))

    def draw(self):
        snapshot = self.simulation.snapshot()
        screen = self.screen
        screen.fill((15, 21, 30))
        self._text("Digital Life Lab", 14, 10)
        self._text(
            f"tick {snapshot['tick']} | t={snapshot['time']:.1f}s | "
            f"pop {len(snapshot['organisms'])} | seed {self.simulation.seed}",
            180,
            10,
        )
        self._text(f"vel. effettiva {self.actual_speed:.1f}x", 790, 10, small=True)
        labels = [
            ("play", "Play" if self.paused else "Pausa"),
            ("tick", "Tick"),
            ("speed", f"Vel. {self.speed}x"),
            ("sensors", "Sensori"),
            ("signals", "Segnali"),
            ("energy", "Energia"),
            ("trails", "Tracce"),
            ("export", "Esporta CSV"),
        ]
        self.buttons = {}
        x = 14
        for key, label in labels:
            button = pygame.Rect(x, 36, 118 if key == "export" else 90, 29)
            self.buttons[key] = button
            active = getattr(self, f"show_{key}", False)
            pygame.draw.rect(
                screen, (39, 87, 83) if active else (39, 50, 65), button, border_radius=4
            )
            self._text(label, button.x + 8, button.y + 6)
            x = button.right + 6
        self.seed_rect = pygame.Rect(62, 73, 150, 28)
        self.buttons["new"] = pygame.Rect(222, 73, 178, 28)
        self._text("Seed:", 14, 79)
        pygame.draw.rect(screen, (44, 65, 79) if self.seed_active else (28, 38, 51), self.seed_rect)
        self._text(self.seed_text, 68, 79)
        pygame.draw.rect(screen, (39, 50, 65), self.buttons["new"], border_radius=4)
        self._text("Nuovo esperimento", 230, 79)
        self._text(self.message[:90], 412, 80, small=True)
        for name, label, x, width in (
            ("save", "Salva .dlcp", 14, 112),
            ("load", "Carica", 134, 82),
            ("recent", "Recenti", 224, 82),
        ):
            self.buttons[name] = pygame.Rect(x, 109, width, 28)
            pygame.draw.rect(screen, (39, 50, 65), self.buttons[name], border_radius=4)
            self._text(label, x + 7, 115)
        self.checkpoint_rect = pygame.Rect(316, 109, max(100, screen.get_width() - 335), 28)
        pygame.draw.rect(
            screen, (44, 65, 79) if self.checkpoint_active else (28, 38, 51), self.checkpoint_rect
        )
        screen.set_clip(self.checkpoint_rect)
        self._text(
            self.checkpoint_text or "Percorso .dlcp (Invio per caricare)", 322, 116, small=True
        )
        screen.set_clip(None)
        viewport, scale, panel_x = self._layout()
        pygame.draw.rect(screen, (23, 32, 40), viewport)
        screen.set_clip(viewport)
        if self.show_signals and snapshot["signals"] is not None:
            field = snapshot["signals"]
            overlay = pygame.Surface((field.shape[2], field.shape[1]), pygame.SRCALPHA)
            total = field.sum(axis=0).T
            fraction = np.divide(field[0].T, total, out=np.zeros_like(total), where=total > 0)
            rgb = pygame.surfarray.pixels3d(overlay)
            rgb[:, :, 0] = (220 - 150 * fraction).astype(np.uint8)
            rgb[:, :, 1] = (110 + 50 * fraction).astype(np.uint8)
            rgb[:, :, 2] = (130 + 80 * fraction).astype(np.uint8)
            del rgb
            alpha = pygame.surfarray.pixels_alpha(overlay)
            alpha[:] = (
                np.clip(total / self.simulation.config.signals.sensor_scale, 0, 1) * 150
            ).astype(np.uint8)
            del alpha
            screen.blit(pygame.transform.smoothscale(overlay, viewport.size), viewport)
        if self.show_trails:
            for organism in snapshot["organisms"]:
                points = self.trails.setdefault(organism["id"], deque(maxlen=180))
                point = self._point(organism["position"], viewport, scale)
                if not points or points[-1] != point:
                    points.append(point)
                if len(points) > 1:
                    pygame.draw.lines(screen, (66, 82, 91), False, list(points), 1)
            living = {o["id"] for o in snapshot["organisms"]}
            self.trails = {i: points for i, points in self.trails.items() if i in living}
        w, b = self.simulation.config.world, self.simulation.config.body
        for position, energy in zip(
            snapshot["resource_positions"], snapshot["resource_energy"], strict=True
        ):
            intensity = energy / w.resource_capacity
            color = (36, int(55 + 130 * intensity), 74)
            pygame.draw.circle(
                screen,
                color,
                self._point(position, viewport, scale),
                max(2, round(w.resource_radius * scale)),
            )
        selected = None
        for organism in snapshot["organisms"]:
            point = self._point(organism["position"], viewport, scale)
            radius = max(3, round(organism["radius"] * scale))
            color = (225, 170 + (organism["lineage_id"] * 7) % 70, 96)
            pygame.draw.circle(screen, color, point, radius)
            angle = organism["orientation"]
            tip = (
                round(point[0] + (radius + 4) * math.cos(angle)),
                round(point[1] + (radius + 4) * math.sin(angle)),
            )
            pygame.draw.line(screen, (249, 244, 218), point, tip, 2)
            if self.show_energy:
                fraction = organism["energy"] / b.energy_capacity
                pygame.draw.line(
                    screen,
                    (83, 106, 113),
                    (point[0] - 7, point[1] - radius - 5),
                    (point[0] + 7, point[1] - radius - 5),
                    2,
                )
                pygame.draw.line(
                    screen,
                    (102, 207, 147),
                    (point[0] - 7, point[1] - radius - 5),
                    (point[0] - 7 + round(14 * fraction), point[1] - radius - 5),
                    2,
                )
            if organism["id"] == self.selected:
                selected = organism
                pygame.draw.circle(screen, (235, 245, 250), point, radius + 4, 1)
                if self.show_sensors:
                    reach = round(self.simulation.config.sensors.range * scale)
                    pygame.draw.circle(screen, (76, 122, 139), point, reach, 1)
                    for offset in (0, math.pi / 2, -math.pi / 2):
                        end = (
                            round(point[0] + reach * math.cos(angle + offset)),
                            round(point[1] + reach * math.sin(angle + offset)),
                        )
                        pygame.draw.line(screen, (76, 122, 139), point, end, 1)
        screen.set_clip(None)
        pygame.draw.rect(screen, (48, 62, 73), viewport, 1)
        self._text(
            "Risorse: verde | Corpi: giallo | Segnali C0: ciano, C1: rosa",
            viewport.x,
            viewport.bottom + 6,
            small=True,
        )
        x, y = panel_x + 12, 155
        self._text("Osservazione", x, y)
        y += 30
        if selected:
            rows = [
                ("ID / genitore", f"{selected['id']} / {selected['parent_id']}"),
                ("Linea / generazione", f"{selected['lineage_id']} / {selected['generation']}"),
                ("Eta / energia", f"{selected['age']:.1f}s / {selected['energy']:.2f}"),
                ("Neuroni / connessioni", f"{selected['neurons']} / {selected['connections']}"),
                (
                    "Acquisita / figli",
                    f"{selected['acquired_energy']:.2f} / {selected['offspring']}",
                ),
            ]
            for label, value in rows:
                self._text(f"{label}: {value}", x, y, small=True)
                y += 21
            y += 8
            self._text("Sensori locali [0, 1]", x, y)
            y += 26
            for name, value in zip(SENSOR_NAMES, selected["sensors"], strict=True):
                self._text(f"{name:18s} {value: .3f}", x, y, small=True)
                y += 17
            y += 8
            self._text("Output neurali", x, y)
            y += 26
            for name, value in zip(OUTPUT_NAMES, selected["outputs"], strict=True):
                self._text(f"{name:18s} {value: .3f}", x, y, small=True)
                y += 18
        elif self.selected is not None:
            self._text(f"Organismo {self.selected}: morto", x, y)
        else:
            self._text("Clicca un organismo per ispezionarlo.", x, y, small=True)
        self._text(
            f"Errore bilancio energia: {snapshot['energy_error']:.2e}",
            x,
            self.screen.get_height() - 37,
            small=True,
        )
        pygame.display.flip()

    def _observe_tick(self):
        try:
            if self.on_tick:
                self.on_tick(self.simulation)
        except (OSError, ValueError, RuntimeError) as error:
            self.paused = True
            self.observation_pending = True
            self.message = str(error)
            return False
        self.observation_pending = False
        return True

    def _command(self, command):
        if command in {"play", "tick"} and self.observation_pending:
            if not self._observe_tick():
                return
        if command in {"save", "load", "recent"}:
            try:
                if command == "save" and self.on_save:
                    self.paused = True
                    self.accumulator = 0
                    self.message = "Salvataggio checkpoint..."
                    self.draw()
                    self.checkpoint_text = str(self.on_save())
                    self.observation_pending = False
                    self.message = "Checkpoint salvato."
                elif command == "load" and self.on_load:
                    self.paused = True
                    replacement = self.on_load(self.checkpoint_text)
                    self.simulation = replacement
                    self.observation_pending = False
                    self.selected = None
                    self.trails.clear()
                    self.accumulator = 0
                    self.actual_speed = 0
                    self.message = f"Checkpoint caricato al tick {replacement.tick}; in pausa."
                elif command == "recent" and self.on_list:
                    choices = self.on_list()
                    if choices:
                        self.recent_index = (self.recent_index + 1) % len(choices)
                        self.checkpoint_text = str(choices[self.recent_index])
                    else:
                        self.message = "Nessun checkpoint disponibile."
            except (OSError, ValueError, RuntimeError) as error:
                self.paused = True
                self.message = str(error)
            return
        if command == "play":
            self.paused = not self.paused
            self.accumulator = 0
        elif command == "tick":
            self.paused = True
            self.accumulator = 0
            self.simulation.step()
            self._observe_tick()
        elif command == "speed":
            speeds = [1, 4, 16, 64]
            self.speed = speeds[(speeds.index(self.speed) + 1) % 4]
        elif command in {"sensors", "signals", "energy", "trails"}:
            attr = f"show_{command}"
            setattr(self, attr, not getattr(self, attr))
            if command == "trails":
                self.trails.clear()
        elif command == "export" and self.on_export:
            self.message = str(self.on_export())
        elif command == "new" and self.on_new:
            try:
                seed = int(self.seed_text)
                if not 0 <= seed < 2**63:
                    raise ValueError
                self.simulation = self.on_new(seed)
                self.observation_pending = False
                self.selected = None
                self.trails.clear()
                self.accumulator = 0
                self.message = f"Nuovo esperimento, seed {seed}"
            except (ValueError, OSError, RuntimeError) as error:
                self.paused = True
                self.message = f"Nuovo esperimento non avviato: {error}"

    def _request_close(self):
        try:
            if self.on_close:
                self.on_close()
            return True
        except (OSError, ValueError, RuntimeError) as error:
            self.paused = True
            self.message = f"Chiusura sospesa; riprova salvataggio: {error}"
            return False

    def run(self, on_tick=None, max_frames: int | None = None, should_stop=None):
        self.on_tick = on_tick
        frames = 0
        running = True
        last_measure = time.perf_counter()
        measured_ticks = 0
        try:
            self.draw()
            while running:
                elapsed = min(self.clock.tick(60) / 1000, 0.25)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        running = not self._request_close()
                    elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                        self.seed_active = self.seed_rect.collidepoint(event.pos)
                        self.checkpoint_active = self.checkpoint_rect.collidepoint(event.pos)
                        for name, rectangle in self.buttons.items():
                            if rectangle.collidepoint(event.pos):
                                self._command(name)
                                break
                        else:
                            viewport, scale, _ = self._layout()
                            if viewport.collidepoint(event.pos):
                                point = (np.array(event.pos) - np.array(viewport.topleft)) / scale
                                nearby = [
                                    (np.linalg.norm(o.position - point), i)
                                    for i, o in self.simulation.world.organisms.items()
                                ]
                                nearest = min(nearby, default=(math.inf, None))
                                if nearest[0] < max(12, 10 / scale):
                                    self.selected = nearest[1]
                    elif event.type == pygame.KEYDOWN:
                        if self.checkpoint_active:
                            if event.key == pygame.K_BACKSPACE:
                                self.checkpoint_text = self.checkpoint_text[:-1]
                            elif event.key == pygame.K_RETURN:
                                self._command("load")
                                self.checkpoint_active = False
                            elif event.unicode and event.unicode.isprintable():
                                self.checkpoint_text += event.unicode
                        elif self.seed_active:
                            if event.key == pygame.K_BACKSPACE:
                                self.seed_text = self.seed_text[:-1]
                            elif event.key == pygame.K_RETURN:
                                self._command("new")
                                self.seed_active = False
                            elif event.unicode.isdecimal() and len(self.seed_text) < 18:
                                self.seed_text += event.unicode
                        elif event.key == pygame.K_SPACE:
                            self._command("play")
                        elif event.key == pygame.K_PERIOD:
                            self._command("tick")
                        elif event.key == pygame.K_ESCAPE:
                            running = not self._request_close()
                if not self.paused and running:
                    dt = self.simulation.config.world.dt
                    self.accumulator = min(self.accumulator + elapsed * self.speed, dt * 256)
                    work_start = time.perf_counter()
                    while self.accumulator >= dt:
                        if should_stop and should_stop():
                            break
                        self.simulation.step()
                        measured_ticks += 1
                        self.accumulator -= dt
                        if not self._observe_tick():
                            break
                        if time.perf_counter() - work_start > 0.025:
                            break
                now = time.perf_counter()
                if now - last_measure >= 0.5:
                    self.actual_speed = (
                        measured_ticks * self.simulation.config.world.dt / (now - last_measure)
                    )
                    measured_ticks = 0
                    last_measure = now
                self.draw()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    if not self._request_close():
                        raise RuntimeError(self.message)
                    running = False
                if should_stop and should_stop():
                    running = not self._request_close()
        finally:
            pygame.quit()
