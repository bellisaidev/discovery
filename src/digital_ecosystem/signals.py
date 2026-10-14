"""Finite-lifetime diffusive fields with exact (up to roundoff) self exclusion.

Two aggregate grids plus bounded sparse emission history replace an entire grid
per individual. Shared powers of 1-D transition operators reconstruct own traces
and expire old emissions using the SAME operator as global field propagation.
"""

import math
from collections import deque

import numpy as np

from .configuration import Configuration


class SignalField:
    def __init__(self, config: Configuration):
        self.config = config
        s, w = config.signals, config.world
        self.field = np.zeros((2, s.rows, s.columns))
        self.tick = 0
        self.history = deque()
        self.own_history = {}
        self.emitted = np.zeros(2)
        self.detectable_emissions = np.zeros(2, dtype=int)
        self.trace_dtype = np.dtype(
            [("tick", "i8"), ("x", "i4"), ("y", "i4"), ("amplitude", "f8", (2,))]
        )
        dx, dy = w.width / max(1, s.columns - 1), w.height / max(1, s.rows - 1)
        self.decay = math.exp(-s.decay * w.dt)
        self.px = self._transition(s.columns, s.diffusion * w.dt / dx**2)
        self.py = self._transition(s.rows, s.diffusion * w.dt / dy**2)
        self.kx = self._powers(self.px, s.lifetime_ticks)
        self.ky = self._powers(self.py, s.lifetime_ticks)
        self.decays = self.decay ** np.arange(s.lifetime_ticks + 1)

    @staticmethod
    def _transition(size: int, ratio: float) -> np.ndarray:
        substeps = max(1, math.ceil(ratio / 0.45))
        r = ratio / substeps
        transition = np.eye(size)
        for i in range(size - 1):
            transition[i, i] -= r
            transition[i + 1, i + 1] -= r
            transition[i + 1, i] += r
            transition[i, i + 1] += r
        return np.linalg.matrix_power(transition, substeps)

    @staticmethod
    def _powers(transition: np.ndarray, lifetime: int) -> np.ndarray:
        powers = [np.eye(len(transition))]
        for _ in range(lifetime):
            powers.append(powers[-1] @ transition)
        return np.array(powers)

    def cell(self, position: np.ndarray) -> tuple[int, int]:
        s, w = self.config.signals, self.config.world
        x = int(np.clip(np.rint(position[0] / w.width * (s.columns - 1)), 0, s.columns - 1))
        y = int(np.clip(np.rint(position[1] / w.height * (s.rows - 1)), 0, s.rows - 1))
        return x, y

    def propagate(self, field: np.ndarray) -> np.ndarray:
        return self.decay * (self.py @ field @ self.px.T)

    def advance(self, emissions: list[tuple[int, np.ndarray, np.ndarray]]) -> None:
        self.tick += 1
        self.field = self.propagate(self.field)
        lifetime = self.config.signals.lifetime_ticks
        if self.history and self.history[0][0] <= self.tick - lifetime:
            old_tick, identifiers, xs, ys, amplitudes = self.history.popleft()
            grid = np.zeros_like(self.field)
            for channel in (0, 1):
                np.add.at(grid[channel], (ys, xs), amplitudes[:, channel])
            for identifier in identifiers:
                own = self.own_history[identifier]
                own["tick"][old_tick % lifetime] = -1
                if not np.any(own["tick"] >= 0):
                    del self.own_history[identifier]
            self.field -= self.decays[lifetime] * (self.ky[lifetime] @ grid @ self.kx[lifetime].T)
        s, w = self.config.signals, self.config.world
        identifiers = np.array([e[0] for e in emissions], dtype=np.int64)
        positions = np.array([e[1] for e in emissions], dtype=float).reshape(-1, 2)
        amplitudes = np.array([e[2] for e in emissions], dtype=float).reshape(-1, 2)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("At most one two-channel emission per organism per tick")
        if len(emissions):
            if not np.all(np.isfinite(amplitudes)) or np.any(amplitudes < 0):
                raise ValueError("Invalid signal emission")
            nonzero = np.any(amplitudes != 0, axis=1)
            identifiers, positions, amplitudes = (
                identifiers[nonzero],
                positions[nonzero],
                amplitudes[nonzero],
            )
        xs = np.clip(np.rint(positions[:, 0] / w.width * (s.columns - 1)), 0, s.columns - 1).astype(
            np.intp
        )
        ys = np.clip(np.rint(positions[:, 1] / w.height * (s.rows - 1)), 0, s.rows - 1).astype(
            np.intp
        )
        for channel in (0, 1):
            np.add.at(self.field[channel], (ys, xs), amplitudes[:, channel])
        self.emitted += amplitudes.sum(axis=0)
        self.detectable_emissions += np.sum(amplitudes > 1e-12, axis=0)
        for identifier, x, y, amplitude in zip(identifiers, xs, ys, amplitudes, strict=True):
            if identifier not in self.own_history:
                trace = np.zeros(lifetime, dtype=self.trace_dtype)
                trace["tick"] = -1
                self.own_history[identifier] = trace
            self.own_history[identifier][self.tick % lifetime] = (self.tick, x, y, amplitude)
        self.history.append((self.tick, identifiers, xs, ys, amplitudes))
        # Numerical cancellation of expired traces may leave ~1e-17 residuals.
        np.maximum(self.field, 0, out=self.field)

    def sample(self, positions: np.ndarray, exclude: int | None = None) -> np.ndarray:
        s, w = self.config.signals, self.config.world
        positions = np.asarray(positions, dtype=float).reshape(-1, 2)
        x = np.clip(positions[:, 0] / w.width * (s.columns - 1), 0, s.columns - 1)
        y = np.clip(positions[:, 1] / w.height * (s.rows - 1), 0, s.rows - 1)
        ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
        fx, fy = x - ix, y - iy
        result = np.zeros((len(positions), 2))
        trace = self.own_history.get(exclude)
        has_own = trace is not None
        if has_own:
            own = trace[trace["tick"] >= 0]
            ages = self.tick - own["tick"]
            ox, oy, amplitudes = own["x"], own["y"], own["amplitude"]
        for offset_x, wx in ((0, 1 - fx), (1, fx)):
            for offset_y, wy in ((0, 1 - fy), (1, fy)):
                tx = np.minimum(ix + offset_x, s.columns - 1)
                ty = np.minimum(iy + offset_y, s.rows - 1)
                values = self.field[:, ty, tx].T.copy()
                if has_own:
                    kernels = (
                        self.kx[ages[None, :], tx[:, None], ox[None, :]]
                        * self.ky[ages[None, :], ty[:, None], oy[None, :]]
                        * self.decays[ages][None, :]
                    )
                    values -= kernels @ amplitudes
                result += (wx * wy)[:, None] * values
        return np.maximum(result, 0)

    def memory_bytes(self) -> int:
        arrays = self.field.nbytes + self.kx.nbytes + self.ky.nbytes
        arrays += self.px.nbytes + self.py.nbytes + self.decays.nbytes
        arrays += sum(
            a.nbytes
            for _, identifiers, xs, ys, amplitudes in self.history
            for a in (identifiers, xs, ys, amplitudes)
        )
        arrays += sum(trace.nbytes for trace in self.own_history.values())
        return arrays
