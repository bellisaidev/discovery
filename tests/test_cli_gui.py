import json
import os
import subprocess
import sys
from pathlib import Path


def test_headless_does_not_import_pygame(tmp_path):
    script = (
        "import sys; from digital_ecosystem.__main__ import main; "
        "main(['--headless','--steps','2','--output',sys.argv[1]]); "
        "assert 'pygame' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True, check=True
    )
    assert json.loads(result.stdout)["tick"] == 2


def test_gui_dummy_launch_and_buttons(tmp_path):
    script = """
import sys
import pygame
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.renderer import Renderer
s = Simulation(Configuration(), 42)
r = Renderer(s, on_new=lambda seed: Simulation(s.config, seed), on_export=lambda: 'exported')
r.on_tick = None
r.draw()
r.selected = 1
r._command('sensors')
r._command('signals')
r._command('energy')
r._command('trails')
r._command('tick')
assert r.paused and r.simulation.tick == 1
for _ in range(3): r._command('speed')
assert r.speed == 64
r._command('export')
assert r.message == 'exported'
r.seed_text = '123'
r._command('new')
assert r.simulation.seed == 123
r.draw()
pygame.image.save(r.screen, sys.argv[1])
r.run(max_frames=2)
"""
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "gui.png")],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (tmp_path / "gui.png").exists()


def test_cli_invalid_config(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "digital_ecosystem",
            "--headless",
            "--config",
            str(Path(tmp_path) / "missing.toml"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2


def test_cli_marks_failure_and_interruptions(tmp_path, monkeypatch):
    import sqlite3

    import pytest

    from digital_ecosystem.__main__ import main
    from digital_ecosystem.simulation import Simulation

    def fail_step(self):
        raise RuntimeError("controlled verification failure")

    monkeypatch.setattr(Simulation, "step", fail_step)
    output = tmp_path / "failure"
    with pytest.raises(RuntimeError, match="controlled"):
        main(["--headless", "--steps", "1", "--output", str(output)])
    with sqlite3.connect(output / "lab.sqlite3") as connection:
        assert connection.execute("SELECT status FROM experiments").fetchone()[0] == "failed"

    def interrupt_step(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(Simulation, "step", interrupt_step)
    output = tmp_path / "interrupted"
    assert main(["--headless", "--steps", "1", "--output", str(output)]) == 130
    with sqlite3.connect(output / "lab.sqlite3") as connection:
        assert connection.execute("SELECT status FROM experiments").fetchone()[0] == "interrupted"
