"""The HTTP surface: routers, schemas and request middleware.

Nothing here decides anything. Routers read, compose and serve; every rule they present was
produced by the engine, and every write they permit goes through the audited unit of work.
"""
