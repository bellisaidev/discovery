"""Offline command line entry point. Headless paths never import Pygame."""

import argparse
import json
from pathlib import Path

from .configuration import Configuration
from .experiment_logger import ExperimentLogger
from .simulation import Simulation


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Digital Life Lab — offline artificial life")
    cli.add_argument("--config", type=Path, help="TOML preset; defaults to experimental parameters")
    cli.add_argument("--headless", action="store_true")
    cli.add_argument("--steps", type=int, default=10000)
    cli.add_argument("--seed", type=int, default=42)
    cli.add_argument("--output", type=Path, default=Path("experiments"))
    cli.add_argument("--no-plasticity", action="store_true")
    cli.add_argument("--no-mutations", action="store_true")
    cli.add_argument("--no-signaling", action="store_true")
    cli.add_argument("--export-csv", action="store_true")
    cli.add_argument("--compare-seeds", help="Comma-separated seeds; runs all eight ablations")
    cli.add_argument("--gui-frames", type=int, help="Exit GUI after N frames (smoke verification)")
    return cli


def main(argv=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    try:
        config = Configuration.load(args.config)
        config.neural.plasticity &= not args.no_plasticity
        config.neural.mutations &= not args.no_mutations
        config.signals.enabled &= not args.no_signaling
        config.validate()
        if args.steps < 0 or not 0 <= args.seed < 2**63:
            raise ValueError("Steps must be nonnegative; seed must be in [0, 2**63 - 1]")
        if args.gui_frames is not None and args.gui_frames <= 0:
            raise ValueError("GUI frame count must be positive")
    except (OSError, ValueError) as error:
        cli.error(str(error))
    if args.compare_seeds:
        from .comparison import run_comparison

        try:
            seeds = [int(value.strip()) for value in args.compare_seeds.split(",")]
            report = run_comparison(config, seeds, args.steps, args.output)
        except ValueError as error:
            cli.error(str(error))
        print(
            json.dumps(
                {
                    "comparison": str(args.output / "comparison.json"),
                    "seeds": report["seeds"],
                    "runs": len(seeds) * 8,
                }
            )
        )
        return 0
    simulation = Simulation(config, args.seed)
    logger = ExperimentLogger(simulation, args.output)
    status = "completed"

    def new_experiment(seed):
        nonlocal simulation, logger
        replacement = Simulation(config, seed)
        logger.close("restarted")
        simulation = replacement
        logger = ExperimentLogger(simulation, args.output)
        return simulation

    try:
        if args.headless:
            for _ in range(args.steps):
                simulation.step()
                logger.observe()
        else:
            from .renderer import Renderer

            Renderer(simulation, on_new=new_experiment, on_export=lambda: logger.export_csv()).run(
                on_tick=lambda current: logger.observe(current), max_frames=args.gui_frames
            )
    except KeyboardInterrupt:
        status = "interrupted"
    except BaseException:
        status = "failed"
        raise
    finally:
        summary = logger.close(status)
        if args.export_csv:
            logger.export_csv()
    print(
        json.dumps(
            {
                "experiment_id": logger.experiment_id,
                "database": str(logger.database),
                "status": status,
                "tick": simulation.tick,
                "population": summary["population"],
                "births": simulation.births,
                "deaths": simulation.deaths,
                "energy_balance_error": summary["balance_error"],
            }
        )
    )
    return 130 if status == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
