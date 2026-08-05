"""CLI bridge used by Liquidsoap to exchange events with station Python."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from catalog_loader import PROJECT_ROOT
from streaming_adapter import (
    StreamingResultStatus,
    deserialize_event,
    send_bridge_command,
)


def liquidsoap_request_uri(
    event_id: str,
    event_payload: object,
    *,
    project_root: str | Path = PROJECT_ROOT,
) -> str:
    """Build one annotated file URI understood by Liquidsoap request sources."""

    event = deserialize_event(event_payload)
    media_path = Path(event.media_path)
    if not media_path.is_absolute():
        media_path = Path(project_root) / media_path
    resolved_path = str(media_path.resolve())
    if "\n" in resolved_path or "\r" in resolved_path:
        raise ValueError("Liquidsoap media paths cannot contain line breaks")

    metadata = [
        ("dcr_event_id", event_id),
        ("dcr_media_type", event.media_type.value),
        ("dcr_media_path", resolved_path),
        ("title", event.display_title),
        ("station_name", event.station_name),
        ("dcr_start_offset", format(event.start_offset, ".17g")),
    ]
    if event.artist is not None:
        metadata.append(("artist", event.artist))
    if event.associated_song_title is not None:
        metadata.append(("dcr_associated_song", event.associated_song_title))

    annotations = ",".join(
        f'{key}="{_escape_annotation(value)}"' for key, value in metadata
    )
    return f"annotate:{annotations}:{resolved_path}"


def _escape_annotation(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--socket",
        required=True,
        type=Path,
        help="Unix-domain socket exposed by LiquidsoapStreamingAdapter",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("next", help="print the next annotated request URI")

    started = subparsers.add_parser("started", help="report event playback start")
    started.add_argument("event_id")

    result = subparsers.add_parser("result", help="report a terminal event result")
    result.add_argument("event_id")
    result.add_argument(
        "status",
        choices=[status.value for status in StreamingResultStatus],
    )
    result.add_argument("--detail")

    source_lost = subparsers.add_parser(
        "source-lost",
        help="report loss of the active Liquidsoap source/control path",
    )
    source_lost.add_argument("--detail")

    subparsers.add_parser("shutdown", help="report a clean Liquidsoap shutdown")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "next":
            response = send_bridge_command(args.socket, {"command": "next"})
            if response.get("type") in {"no_event", "shutdown"}:
                print("DCR_NO_EVENT")
                return 0
            if response.get("type") != "event":
                raise RuntimeError(f"unexpected broker response: {response!r}")
            print(response["event_id"])
            print(
                liquidsoap_request_uri(
                    response["event_id"],
                    response["event"],
                )
            )
            return 0

        if args.command == "started":
            command = {"command": "started", "event_id": args.event_id}
        elif args.command == "result":
            command = {
                "command": "result",
                "event_id": args.event_id,
                "status": args.status,
                "detail": args.detail,
            }
        elif args.command == "source-lost":
            command = {"command": "source_lost", "detail": args.detail}
        else:
            command = {"command": "shutdown"}

        response = send_bridge_command(args.socket, command)
        if response.get("type") != "ack":
            raise RuntimeError(f"broker rejected command: {response!r}")
        return 0
    except (OSError, KeyError, RuntimeError, ValueError) as error:
        print(f"streaming bridge error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
