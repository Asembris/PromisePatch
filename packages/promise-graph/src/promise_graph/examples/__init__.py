"""Example datasets that ship with the engine.

The Hollow Oak Bakery fixture lives here rather than in the test suite because more than one
consumer needs it: the engine's own tests, and any application that persists the same graph
and must prove its stored copy still yields identical decisions.

These modules are data, not engine. They are held to the same purity rules — standard
library and Pydantic only, no clock, no environment — but they are not part of the
decision surface, and nothing in ``promise_graph`` imports them.
"""
