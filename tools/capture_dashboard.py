"""Capture the dashboard from actual SQLite records, without starting a simulation."""

import argparse
import os
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--experiment")
    parser.add_argument("--group", default="Popolazione")
    parser.add_argument("--output", type=Path, default=Path("docs/m6-dashboard.png"))
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    if not args.real:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    from digital_ecosystem.dashboard import DashboardRenderer
    from digital_ecosystem.observations import ExperimentReader

    reader = ExperimentReader(args.database)
    rows = reader.experiments(limit=1)
    identifier = args.experiment or rows[0]["id"]
    reader.close()
    renderer = DashboardRenderer(browse=args.database, experiment_id=identifier)
    renderer.group = args.group
    try:
        deadline = time.perf_counter() + 10
        while time.perf_counter() < deadline:
            renderer.draw()
            if renderer.data is not None or args.group == "Genealogia":
                break
            time.sleep(0.01)
        if args.group != "Genealogia" and renderer.data is None:
            raise RuntimeError(renderer.message or "Dashboard did not finish loading")
        if args.group == "Genealogia" and renderer.tree:
            for node_id in list(renderer.tree.nodes)[:4]:
                renderer.tree.toggle(node_id)
            renderer.genealogy = renderer.tree.rows()
            renderer.draw()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(renderer.screen, args.output)
        print(
            {
                "output": str(args.output),
                "driver": pygame.display.get_driver(),
                "experiment_id": identifier,
                "group": args.group,
            }
        )
    finally:
        renderer.run(max_frames=1)


if __name__ == "__main__":
    main()
