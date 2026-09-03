"""The graph read model: stored rows in, a pure ``promise_graph`` snapshot out."""

from promisepatch.graph.channel import join_channel, split_channel

__all__ = ["join_channel", "split_channel"]
