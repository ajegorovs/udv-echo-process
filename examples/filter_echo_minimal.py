"""Minimal echo -> filter: load a recording, pick a channel, filter it.

    uv run python examples/filter_echo_minimal.py

The artifact path ships no plot function for a ChannelBundle (``viz.py`` rides
the ``.ADD``/ExtractedData path), so the only pre-defined summary available
here is ``ChannelConfig.describe()`` — printed at the end.
"""

from __future__ import annotations

from udv_echo_process import MedianFilterSpec, filter, load
from udv_echo_process.models import ChannelKey
from udv_echo_process.provenance import select_channel

# .BDD -> ArtifactBundle = Recording + provenance graph
bundle = load("data/echo/650.BDD")
# recording level -> one channel's ChannelBundle
channel = select_channel(bundle, ChannelKey(device_channel=4))
# ChannelBundle -> ChannelBundle (the transform shadows the builtin here)
filtered = filter(channel, MedianFilterSpec(window=5, max_gap_s=0.04))

# the one pre-defined summary on this path: ChannelConfig.describe()
print(filtered.artifact.config.describe())
