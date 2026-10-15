"""Capture the actual integrated observation UI, without changing physical rules."""

import os
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from digital_ecosystem.configuration import Configuration
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.observations import ExperimentReader, ObservationWriter
from digital_ecosystem.renderer import Renderer
from digital_ecosystem.simulation import Simulation


def main():
    simulation = Simulation(Configuration.load("configs/diagnostic.toml"), 42)
    logger = ExperimentLogger(simulation, Path("experiments/observation-screenshot"))
    for _ in range(120):
        simulation.step()
        logger.observe()
    writer = ObservationWriter(logger)
    child = next(o for o in simulation.world.organisms.values() if o.parent_id)
    writer.capture(child.id)
    renderer = Renderer(
        simulation,
        on_reader=lambda: ExperimentReader(
            connection=logger.connection, experiment_id=logger.experiment_id
        ),
        on_capture=writer.capture,
    )
    renderer.selected = child.id
    renderer.view = "inspector"
    renderer.paused = True
    renderer.inspector.ancestor_id = child.parent_id
    renderer.inspector.node = 16
    renderer.draw()
    pygame.image.save(renderer.screen, "docs/m5-inspector.png")
    logger.close()
    pygame.quit()


if __name__ == "__main__":
    main()
