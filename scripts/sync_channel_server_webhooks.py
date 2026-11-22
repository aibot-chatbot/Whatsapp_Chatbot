"""List connected linked-device sessions. --apply replaces their webhook config and restarts them."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.channel_server_repository import list_connected_sessions
from app.services.channel_server_service import ChannelServerError, ensure_session_webhooks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    rows = list_connected_sessions()
    print("Count", len(rows))
    failed = False
    for row in rows:
        if not args.apply:
            print(row["id"])
            continue
        try:
            ensure_session_webhooks(row["session_name"])
        except ChannelServerError:
            print(row["id"], "failed")
            failed = True
        else:
            print(row["id"], "ok")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
