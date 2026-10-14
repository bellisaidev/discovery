"""Offline CLI and session coordination; default arguments never override resumes."""

import argparse
import json
import signal
from pathlib import Path

from .checkpoint import CheckpointManager, read_checkpoint, resume, resume_prepared
from .configuration import Configuration
from .experiment_logger import ExperimentLogger
from .simulation import Simulation


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="Digital Life Lab — offline artificial life")
    cli.add_argument("--config", type=Path, default=None)
    cli.add_argument("--resume", type=Path, default=None)
    cli.add_argument("--headless", action="store_true")
    cli.add_argument("--steps", type=int, default=None, help="Additional ticks; default 10000")
    cli.add_argument("--seed", type=int, default=None)
    cli.add_argument("--output", type=Path, default=None)
    cli.add_argument("--no-plasticity", action="store_true", default=None)
    cli.add_argument("--no-mutations", action="store_true", default=None)
    cli.add_argument("--no-signaling", action="store_true", default=None)
    cli.add_argument("--export-csv", action="store_true")
    cli.add_argument("--compare-seeds", default=None)
    cli.add_argument("--gui-frames", type=int, default=None)
    return cli


def main(argv=None) -> int:
    cli = parser()
    args = cli.parse_args(argv)
    steps = 10000 if args.steps is None else args.steps
    try:
        if steps < 0 or (args.seed is not None and not 0 <= args.seed < 2**63):
            raise ValueError("Steps must be nonnegative; seed must be in [0, 2**63 - 1]")
        if args.gui_frames is not None and args.gui_frames <= 0:
            raise ValueError("GUI frame count must be positive")
        if args.resume is not None:
            if any(
                value is not None
                for value in (
                    args.config,
                    args.seed,
                    args.no_plasticity,
                    args.no_mutations,
                    args.no_signaling,
                    args.compare_seeds,
                )
            ):
                raise ValueError(
                    "--resume rejects explicit seed, config, --no-* and comparison flags"
                )
            simulation, logger = resume(args.resume, args.output)
            config = simulation.config
        else:
            config = Configuration.load(args.config)
            config.neural.plasticity &= not args.no_plasticity
            config.neural.mutations &= not args.no_mutations
            config.signals.enabled &= not args.no_signaling
            config.validate()
            if args.compare_seeds is not None:
                from .comparison import run_comparison

                seeds = [int(value.strip()) for value in args.compare_seeds.split(",")]
                output = args.output or Path("experiments")
                report = run_comparison(config, seeds, steps, output)
                print(
                    json.dumps(
                        {
                            "comparison": str(output / "comparison.json"),
                            "seeds": report["seeds"],
                            "runs": len(seeds) * 8,
                        }
                    )
                )
                return 0
            simulation = Simulation(config, 42 if args.seed is None else args.seed)
            logger = ExperimentLogger(simulation, args.output or Path("experiments"))
    except (OSError, ValueError, RuntimeError) as error:
        cli.error(str(error))
    manager = CheckpointManager(logger)
    status = "completed"
    stop_requested = False

    def request_stop(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    previous_handler = signal.signal(signal.SIGINT, request_stop)

    def observe(current):
        logger.observe(current)
        manager.maybe_save()

    def save():
        return manager.save("manual")

    def new_experiment(seed):
        nonlocal simulation, logger, manager
        replacement = Simulation(config, seed)
        output = logger.output
        manager.save("replaced")
        logger.close("restarted")
        simulation = replacement
        logger = ExperimentLogger(simulation, output)
        manager = CheckpointManager(logger)
        return simulation

    def load(path):
        nonlocal simulation, logger, manager, config
        with read_checkpoint(Path(path)) as (replacement, manifest, snapshot):
            saved = manager.save("replaced")
            original, output = simulation, logger.output
            logger.close("restarted")
            try:
                replacement, replacement_logger = resume_prepared(
                    replacement, manifest, snapshot, output
                )
            except BaseException:
                _, logger = resume(saved, output)
                logger.simulation = original
                manager = CheckpointManager(logger)
                raise
            simulation, logger = replacement, replacement_logger
            config = simulation.config
            manager = CheckpointManager(logger)
            return simulation

    try:
        if args.headless:
            for _ in range(steps):
                if stop_requested:
                    status = "interrupted"
                    break
                simulation.step()
                observe(simulation)
            if stop_requested:
                status = "interrupted"
        else:
            from .renderer import Renderer

            renderer = Renderer(
                simulation,
                on_new=new_experiment,
                on_export=lambda: logger.export_csv(),
                on_save=save,
                on_load=load,
                on_list=lambda: sorted(
                    logger.output.glob("checkpoints/**/*.dlcp"),
                    key=lambda p: p.stat().st_mtime_ns,
                    reverse=True,
                ),
                on_close=lambda: manager.save("close"),
            )
            renderer.paused = args.resume is not None
            renderer.checkpoint_text = "" if args.resume is None else str(args.resume)
            renderer.run(
                on_tick=observe, max_frames=args.gui_frames, should_stop=lambda: stop_requested
            )
            if stop_requested:
                status = "interrupted"
    except KeyboardInterrupt:
        status = "interrupted"
    except BaseException:
        status = "failed"
        raise
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        try:
            if status != "failed" and simulation.at_tick_boundary:
                manager.save("close")
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
                "checkpoint": str(manager.last_path),
                "checkpoint_measurements": manager.measurements,
            }
        )
    )
    return 130 if status == "interrupted" else 0


if __name__ == "__main__":
    raise SystemExit(main())
