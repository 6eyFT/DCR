"""One-event-at-a-time transport boundary for an external streaming engine."""

from __future__ import annotations

import json
import math
import socket
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from playback_events import MediaType, PlaybackEvent


PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1024 * 1024


class StreamingResultStatus(str, Enum):
    COMPLETED = "completed"
    START_FAILED = "start_failed"
    INTERRUPTED = "interrupted"
    CONNECTION_LOST = "connection_lost"


@dataclass(frozen=True)
class StreamingResult:
    event_id: str
    status: StreamingResultStatus
    detail: str | None = None
    submitted_at: float | None = None
    delivered_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None

    @property
    def completed(self) -> bool:
        return self.status is StreamingResultStatus.COMPLETED


class StreamingAdapter(Protocol):
    def play(self, event: PlaybackEvent) -> StreamingResult:
        """Submit one event and wait for its terminal streaming result."""

    def close(self) -> None:
        """Stop accepting events and release transport resources."""


class StreamingProtocolError(ValueError):
    """Raised for malformed or out-of-order streaming protocol messages."""


def serialize_event(event: PlaybackEvent) -> dict[str, object]:
    """Return the protocol representation of every playback-event field."""

    return {
        "media_path": event.media_path,
        "media_type": event.media_type.value,
        "display_title": event.display_title,
        "station_name": event.station_name,
        "artist": event.artist,
        "associated_song_title": event.associated_song_title,
        "start_offset": event.start_offset,
    }


def deserialize_event(payload: object) -> PlaybackEvent:
    """Validate and reconstruct a playback event received over the protocol."""

    if not isinstance(payload, dict):
        raise StreamingProtocolError("event must be a JSON object")

    expected_fields = {
        "media_path",
        "media_type",
        "display_title",
        "station_name",
        "artist",
        "associated_song_title",
        "start_offset",
    }
    if set(payload) != expected_fields:
        missing = sorted(expected_fields - set(payload))
        unexpected = sorted(set(payload) - expected_fields)
        details = []
        if missing:
            details.append(f"missing fields: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected fields: {', '.join(unexpected)}")
        raise StreamingProtocolError("invalid event fields; " + "; ".join(details))

    for field in ("media_path", "display_title", "station_name"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise StreamingProtocolError(f"event field '{field}' must be a non-empty string")

    for field in ("artist", "associated_song_title"):
        if payload[field] is not None and not isinstance(payload[field], str):
            raise StreamingProtocolError(f"event field '{field}' must be a string or null")

    offset = payload["start_offset"]
    if (
        isinstance(offset, bool)
        or not isinstance(offset, (int, float))
        or not math.isfinite(offset)
        or offset < 0
    ):
        raise StreamingProtocolError(
            "event field 'start_offset' must be a finite non-negative number"
        )

    try:
        media_type = MediaType(payload["media_type"])
    except (TypeError, ValueError) as error:
        raise StreamingProtocolError(
            f"event field 'media_type' is invalid: {payload['media_type']!r}"
        ) from error

    return PlaybackEvent(
        media_path=payload["media_path"],
        media_type=media_type,
        display_title=payload["display_title"],
        station_name=payload["station_name"],
        artist=payload["artist"],
        associated_song_title=payload["associated_song_title"],
        start_offset=float(offset),
    )


def send_bridge_command(
    socket_path: str | Path,
    command: dict[str, object],
    *,
    timeout: float = 5.0,
) -> dict[str, object]:
    """Exchange one JSON-lines request with a running adapter broker."""

    wire_command = {
        "protocol_version": PROTOCOL_VERSION,
        **command,
    }
    encoded = (json.dumps(wire_command, ensure_ascii=False) + "\n").encode("utf-8")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(encoded)
        response = _receive_json_line(client)

    if not isinstance(response, dict):
        raise StreamingProtocolError("bridge response must be a JSON object")
    return response


@dataclass
class _PendingEvent:
    event_id: str
    event: PlaybackEvent
    submitted_at: float
    state: str = "queued"
    delivered_at: float | None = None
    started_at: float | None = None
    result: StreamingResult | None = None


class LiquidsoapStreamingAdapter:
    """Broker events and outcomes between station Python and Liquidsoap.

    The adapter deliberately owns no station policy. ``play`` allows only one
    in-flight event, while short-lived bridge clients fetch or report that
    event through a versioned JSON-lines protocol over a Unix-domain socket.
    """

    def __init__(
        self,
        socket_path: str | Path,
        *,
        start_timeout: float = 30.0,
        result_timeout: float = 3600.0,
        event_wait_timeout: float = 1.0,
    ):
        if start_timeout <= 0:
            raise ValueError("start_timeout must be positive")
        if result_timeout <= 0:
            raise ValueError("result_timeout must be positive")
        if event_wait_timeout <= 0:
            raise ValueError("event_wait_timeout must be positive")

        self.socket_path = Path(socket_path)
        self._start_timeout = start_timeout
        self._result_timeout = result_timeout
        self._event_wait_timeout = event_wait_timeout
        self._condition = threading.Condition()
        self._play_lock = threading.Lock()
        self._pending: _PendingEvent | None = None
        self._closed = False
        self._next_event_number = 1

        if self.socket_path.exists():
            raise FileExistsError(
                f"streaming socket path already exists: {self.socket_path}"
            )
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._server.bind(str(self.socket_path))
            self._server.listen(4)
            self._server.settimeout(0.2)
        except OSError:
            self._server.close()
            raise
        self._thread = threading.Thread(
            target=self._serve,
            name="dcr-streaming-broker",
            daemon=True,
        )
        self._thread.start()

    def __enter__(self) -> LiquidsoapStreamingAdapter:
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self.close()

    def play(self, event: PlaybackEvent) -> StreamingResult:
        if not isinstance(event, PlaybackEvent):
            raise TypeError("event must be a PlaybackEvent")

        with self._play_lock:
            with self._condition:
                if self._closed:
                    raise RuntimeError("streaming adapter is closed")

                event_id = f"dcr-{self._next_event_number:08d}"
                self._next_event_number += 1
                pending = _PendingEvent(
                    event_id=event_id,
                    event=event,
                    submitted_at=time.monotonic(),
                )
                self._pending = pending
                self._condition.notify_all()

                start_deadline = time.monotonic() + self._start_timeout
                while pending.result is None:
                    if pending.state == "started":
                        if pending.started_at is None:
                            raise RuntimeError("started event is missing its start time")
                        result_deadline = pending.started_at + self._result_timeout
                        remaining = result_deadline - time.monotonic()
                        if remaining <= 0:
                            pending.result = self._make_result(
                                pending,
                                StreamingResultStatus.CONNECTION_LOST,
                                "streaming source stopped reporting during playback",
                            )
                            break
                        self._condition.wait(timeout=remaining)
                        continue

                    remaining = start_deadline - time.monotonic()
                    if remaining <= 0:
                        status = (
                            StreamingResultStatus.START_FAILED
                            if pending.state == "delivered"
                            else StreamingResultStatus.CONNECTION_LOST
                        )
                        detail = (
                            "Liquidsoap did not report that the delivered event started"
                            if pending.state == "delivered"
                            else "streaming source did not request the queued event"
                        )
                        pending.result = self._make_result(pending, status, detail)
                        break
                    self._condition.wait(timeout=remaining)

                result = pending.result
                self._pending = None
                self._condition.notify_all()

            if result is None:  # pragma: no cover - guarded by the loop above
                raise RuntimeError("streaming event ended without a result")
            return result

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            self._closed = True
            if self._pending is not None and self._pending.result is None:
                self._pending.result = self._make_result(
                    self._pending,
                    StreamingResultStatus.INTERRUPTED,
                    "streaming adapter shut down cleanly",
                )
            self._condition.notify_all()

        self._server.close()
        self._thread.join(timeout=2.0)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def _serve(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
            try:
                connection, _address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return

            threading.Thread(
                target=self._handle_connection,
                args=(connection,),
                name="dcr-streaming-control",
                daemon=True,
            ).start()

    def _handle_connection(self, connection: socket.socket) -> None:
        with connection:
            try:
                request = _receive_json_line(connection)
                response = self._handle_command(request)
            except (StreamingProtocolError, UnicodeError, json.JSONDecodeError) as error:
                response = {"type": "error", "reason": str(error)}
            try:
                connection.sendall(
                    (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                )
            except OSError:
                # Bridge clients are intentionally short-lived. A dropped
                # control connection must not stop the broker accept loop.
                pass

    def _handle_command(self, request: object) -> dict[str, object]:
        if not isinstance(request, dict):
            raise StreamingProtocolError("bridge request must be a JSON object")
        if request.get("protocol_version") != PROTOCOL_VERSION:
            raise StreamingProtocolError(
                f"unsupported protocol version: {request.get('protocol_version')!r}"
            )

        command = request.get("command")
        if command == "next":
            return self._next_event()
        if command == "started":
            return self._mark_started(request.get("event_id"))
        if command == "result":
            return self._mark_result(
                request.get("event_id"),
                request.get("status"),
                request.get("detail"),
            )
        if command == "source_lost":
            return self._mark_source_lost(request.get("detail"))
        if command == "shutdown":
            return self._mark_source_lost("Liquidsoap shut down")
        raise StreamingProtocolError(f"unknown bridge command: {command!r}")

    def _next_event(self) -> dict[str, object]:
        deadline = time.monotonic() + self._event_wait_timeout
        with self._condition:
            while not self._closed:
                if self._pending is not None and self._pending.state == "queued":
                    self._pending.state = "delivered"
                    self._pending.delivered_at = time.monotonic()
                    self._condition.notify_all()
                    return {
                        "type": "event",
                        "event_id": self._pending.event_id,
                        "event": serialize_event(self._pending.event),
                    }
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {"type": "no_event"}
                self._condition.wait(timeout=remaining)
        return {"type": "shutdown"}

    def _mark_started(self, event_id: object) -> dict[str, object]:
        with self._condition:
            pending = self._matching_pending(event_id)
            if pending.state != "delivered":
                raise StreamingProtocolError(
                    f"event {pending.event_id} cannot start from state {pending.state}"
                )
            pending.state = "started"
            pending.started_at = time.monotonic()
            self._condition.notify_all()
            return {"type": "ack", "event_id": pending.event_id}

    def _mark_result(
        self,
        event_id: object,
        status_value: object,
        detail: object,
    ) -> dict[str, object]:
        try:
            status = StreamingResultStatus(status_value)
        except (TypeError, ValueError) as error:
            raise StreamingProtocolError(
                f"invalid terminal status: {status_value!r}"
            ) from error
        if detail is not None and not isinstance(detail, str):
            raise StreamingProtocolError("result detail must be a string or null")

        with self._condition:
            pending = self._matching_pending(event_id)
            if pending.result is not None:
                raise StreamingProtocolError(
                    f"event {pending.event_id} already has a terminal result"
                )
            if status is StreamingResultStatus.COMPLETED and pending.state != "started":
                raise StreamingProtocolError(
                    f"event {pending.event_id} cannot complete before it starts"
                )
            pending.result = self._make_result(pending, status, detail)
            self._condition.notify_all()
            return {"type": "ack", "event_id": pending.event_id}

    def _mark_source_lost(self, detail: object) -> dict[str, object]:
        if detail is not None and not isinstance(detail, str):
            raise StreamingProtocolError("source-loss detail must be a string or null")
        with self._condition:
            if self._pending is not None and self._pending.result is None:
                self._pending.result = self._make_result(
                    self._pending,
                    StreamingResultStatus.CONNECTION_LOST,
                    detail,
                )
                self._condition.notify_all()
            return {"type": "ack"}

    def source_lost(self, detail: str) -> None:
        """Wake an in-flight event when the supervised source process exits."""

        self._mark_source_lost(detail)

    @staticmethod
    def _make_result(
        pending: _PendingEvent,
        status: StreamingResultStatus,
        detail: str | None,
    ) -> StreamingResult:
        return StreamingResult(
            event_id=pending.event_id,
            status=status,
            detail=detail,
            submitted_at=pending.submitted_at,
            delivered_at=pending.delivered_at,
            started_at=pending.started_at,
            finished_at=time.monotonic(),
        )

    def _matching_pending(self, event_id: object) -> _PendingEvent:
        if not isinstance(event_id, str) or not event_id:
            raise StreamingProtocolError("event_id must be a non-empty string")
        if self._pending is None or self._pending.event_id != event_id:
            raise StreamingProtocolError(f"event is not pending: {event_id}")
        return self._pending


def _receive_json_line(connection: socket.socket) -> object:
    chunks = bytearray()
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            raise StreamingProtocolError("connection closed before a complete message")
        chunks.extend(chunk)
        if len(chunks) > MAX_MESSAGE_BYTES:
            raise StreamingProtocolError("streaming protocol message is too large")
        newline = chunks.find(b"\n")
        if newline >= 0:
            return json.loads(chunks[:newline].decode("utf-8"))
