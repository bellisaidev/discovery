"""Read-only integrity summary for an experiment database."""

import argparse
import json
import sqlite3
from pathlib import Path


def inspect(database):
    with sqlite3.connect(f"file:{database.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        reports = []
        for experiment in connection.execute("SELECT * FROM experiments ORDER BY started_at"):
            identifier = experiment["id"]
            samples = connection.execute(
                "SELECT min(tick), max(tick), count(*), "
                "max(abs(balance_error)) FROM samples WHERE experiment_id=?",
                (identifier,),
            ).fetchone()
            last_alive = connection.execute(
                "SELECT max(tick) FROM samples WHERE experiment_id=? AND population>0",
                (identifier,),
            ).fetchone()[0]
            deaths = connection.execute(
                "SELECT count(*) FROM events WHERE experiment_id=? AND kind='death'", (identifier,)
            ).fetchone()[0]
            report = {
                "experiment_id": identifier,
                "seed": experiment["seed"],
                "status": experiment["status"],
                "first_tick": samples[0],
                "last_tick": samples[1],
                "samples": samples[2],
                "max_absolute_balance_error": samples[3],
                "last_alive_sample_tick": last_alive,
                "death_events": deaths,
                "resources_rows": connection.execute(
                    "SELECT count(*) FROM resources WHERE experiment_id=?", (identifier,)
                ).fetchone()[0],
                "summary": json.loads(experiment["summary_json"] or "null"),
                "software": json.loads(experiment["software_json"]),
            }
            reports.append(report)
        return {
            "database": str(database),
            "sqlite_integrity_check": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "experiments": reports,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    text = json.dumps(inspect(args.database), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
