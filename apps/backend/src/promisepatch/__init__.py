"""PromisePatch backend.

Three entrypoints share one package and one image: ``api`` (the HTTP surface), ``worker``
(the durable continuation loop) and ``mcp`` (the intent tool server). Only ``api`` exists so
far.

The backend never re-implements a decision the engine already owns: reachability,
availability, classification, option validation, fingerprinting and revalidation all live in
``promise_graph``, and this package persists, authorises and serves their results.
"""

__version__ = "0.1.0"
