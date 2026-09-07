"""Operator scripts: the composition roots that are not allowed to live inside a package.

Two import-linter contracts make this directory necessary rather than convenient.
``promisepatch`` may not import ``evals``, and ``evals`` may not import an AWS SDK or
``promisepatch.integrations``. A live benchmark needs both halves in one process, so the place
they meet has to be outside both -- and it has to be importable, because a composition root
nobody can import is a composition root nobody can test.

Nothing here is imported by the application, the engine, the wire contract, the order system or
the evaluation package. These are entry points, run by a person or by CI, and they hold no rule
anything else depends on.
"""
