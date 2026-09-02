"""Deterministic promise-graph engine.

Pure Python. Standard library and Pydantic only. No I/O, no environment reads, no wall
clock: every function that needs the current time takes ``now`` as an explicit parameter.
"""
