"""Read models: persisted state and engine output composed into API responses.

Nothing in here decides anything. A view reads a snapshot the loader built and numbers the
engine computed, arranges them, and states the order and the horizon it used.
"""
