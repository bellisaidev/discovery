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


def test_gui_checkpoint_save_load_and_failed_close(tmp_path):
    script = """
import sys
from pathlib import Path
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.checkpoint import CheckpointManager,resume
from digital_ecosystem.renderer import Renderer
s=Simulation(seed=77)
l=ExperimentLogger(s,Path(sys.argv[1]))
m=CheckpointManager(l)
r=Renderer(s,on_save=m.save,on_list=lambda:list(m.directory.glob('*.dlcp')))
r.draw()
r._command('save')
p=Path(r.checkpoint_text)
assert p.is_file() and r.paused
l.close()
holders=[]
def load(path):
    new,logger=resume(Path(path),Path(sys.argv[1])/'copy')
    holders.append(logger)
    return new
r.on_load=load
r._command('load')
assert r.simulation.seed==77 and r.simulation.tick==0 and r.paused
r._command('recent')
assert r.checkpoint_text
old=r.simulation
r.checkpoint_text=str(Path(sys.argv[1])/'missing.dlcp')
r._command('load')
assert r.simulation is old and r.paused
def fail(): raise OSError('disk unavailable')
r.on_close=fail
assert not r._request_close()
r.on_close=None
r.run(max_frames=2)
for logger in holders: logger.close()
"""
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_gui_retries_failed_observation_before_advancing(tmp_path):
    script = """
import sys
from pathlib import Path
from digital_ecosystem.configuration import Configuration
from digital_ecosystem.simulation import Simulation
from digital_ecosystem.experiment_logger import ExperimentLogger
from digital_ecosystem.renderer import Renderer
s=Simulation(Configuration.load('configs/diagnostic.toml'))
l=ExperimentLogger(s,Path(sys.argv[1]))
r=Renderer(s)
r.on_tick=lambda current:l.observe(current,force=True)
l.connection.execute("CREATE TEMP TRIGGER fail BEFORE INSERT ON individuals "
                     "BEGIN SELECT RAISE(FAIL,'failed observation'); END")
l.connection.commit()
r._command('tick')
assert s.tick==1 and r.paused and r.observation_pending
r._command('play')
assert s.tick==1 and r.paused and r.observation_pending
r._command('tick')
assert s.tick==1 and r.paused and r.observation_pending
l.connection.execute('DROP TRIGGER fail')
l.connection.commit()
r._command('play')
assert s.tick==1 and not r.paused and not r.observation_pending
count=l.connection.execute('SELECT count(*) FROM resources WHERE tick=1').fetchone()[0]
assert count==len(s.world.resource_energy)
assert l.connection.execute('SELECT count(*) FROM individuals').fetchone()[0]==20
r._command('tick')
assert s.tick==2
l.close()
r.run(max_frames=1)
stopped=[False]
def stop_after_tick(current): stopped[0]=True
second=Renderer(Simulation(seed=42))
second.speed=64
second.accumulator=second.simulation.config.world.dt*10
second.run(on_tick=stop_after_tick,should_stop=lambda:stopped[0],max_frames=5)
assert second.simulation.tick==1
"""
    env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_sigint_request_finishes_current_tick_before_checkpoint(tmp_path, monkeypatch):
    import signal

    from digital_ecosystem.__main__ import main
    from digital_ecosystem.checkpoint import read_checkpoint
    from digital_ecosystem.simulation import Simulation

    original_step = Simulation.step

    def request_stop_inside_step(self):
        signal.raise_signal(signal.SIGINT)
        original_step(self)

    monkeypatch.setattr(Simulation, "step", request_stop_inside_step)
    assert main(["--headless", "--steps", "10", "--output", str(tmp_path)]) == 130
    checkpoint = next(tmp_path.glob("checkpoints/**/*.dlcp"))
    with read_checkpoint(checkpoint) as (restored, _, _):
        assert restored.tick == 1 and restored.at_tick_boundary
