"""Compatibility wrapper around the shared block executor."""

from block_player import BlockPlayer
from playback_events import PlaybackPlanner
from streaming_adapter import StreamingAdapter


class StreamingBlockPlayer(BlockPlayer):
    def __init__(self, planner: PlaybackPlanner, adapter: StreamingAdapter):
        super().__init__(planner, lambda event: adapter.play(event).completed)
