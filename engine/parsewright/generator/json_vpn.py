"""Synthetic Acme VPN JSON logs plus their truth manifest (event count and true epochs).

Deterministic (fixed seed). Only documentation IP ranges and example.com names are used.
Run: python -m parsewright.generator.json_vpn  (rewrites the fixtures in fixtures/)
"""

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

FIXTURES = Path(__file__).parent / "fixtures"
START = datetime(2026, 10, 20, 8, 0, 0, tzinfo=UTC)
USERS = ["alice", "bob", "carol", "dave", "erin"]
SRC_NETS = ["192.0.2.", "198.51.100."]


def events(n: int, seed: int) -> list[tuple[datetime, dict]]:
    rng = random.Random(seed)  # noqa: S311  # nosec B311 - synthetic data, not security
    out, t = [], START
    for i in range(n):
        t += timedelta(seconds=rng.randint(5, 90))
        kind = rng.choice(["auth", "auth", "session"])
        event = {"event_id": 1000 + i, "type": kind, "user": f"{rng.choice(USERS)}@example.com"}
        event["src_ip"] = f"{rng.choice(SRC_NETS)}{rng.randint(1, 254)}"
        if kind == "auth":
            event["result"] = rng.choice(["success", "success", "failure"])
        else:
            event["dest_ip"] = f"203.0.113.{rng.randint(1, 254)}"
            event["bytes_out"] = rng.randint(200, 90000)
        out.append((t, event))
    return out


def write(name: str, n: int, seed: int, zone: str | None) -> None:
    """zone=None: ISO timestamps with an offset. Otherwise local time in zone, with no offset."""
    lines, epochs = [], []
    for t, event in events(n, seed):
        if zone is None:
            stamp = t.isoformat()
        else:
            stamp = t.astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M:%S")
        lines.append(json.dumps({"time": stamp, **event}, separators=(",", ":")))
        epochs.append(int(t.timestamp()))
    (FIXTURES / f"{name}.json").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest = {
        "source": f"{name}.json",
        "event_count": n,
        "epochs": epochs,
        "true_timezone": zone or "offset in each timestamp",
        "synthetic": True,
    }
    (FIXTURES / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")


def main() -> None:
    write("acme_vpn", 60, seed=7, zone=None)
    write("acme_vpn_notz", 60, seed=11, zone="Asia/Tokyo")  # demo/01: the missing-TZ fix loop


if __name__ == "__main__":
    main()
