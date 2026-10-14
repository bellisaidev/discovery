"""Render a reproducible inspection screenshot (use SDL_VIDEODRIVER=dummy in CI)."""

import argparse
from pathlib import Path

import pygame

from digital_ecosystem.renderer import Renderer
from digital_ecosystem.simulation import Simulation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/gui.png"))
    args = parser.parse_args()
    simulation = Simulation(seed=42)
    for _ in range(120):
        simulation.step()
    renderer = Renderer(simulation)
    renderer.selected = 1
    renderer.show_sensors = True
    renderer.paused = True
    renderer.draw()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(renderer.screen, args.output)
    pygame.quit()
    print(args.output)


if __name__ == "__main__":
    main()
