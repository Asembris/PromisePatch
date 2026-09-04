"""The durable workflow: what a step decides, and what makes the decision survive a restart.

The package has two halves and the boundary between them is the point.

:mod:`~promisepatch.domain.model`, :mod:`~promisepatch.domain.handlers` and
:mod:`~promisepatch.domain.retry` are **pure**. They take a description of a step and the state
it is running against, and return a description of what should be persisted. They open no
connection, call no provider, read no clock and import nothing from the web or database layers,
so what a step decides is decided by its inputs and can be tested without either.

:mod:`~promisepatch.domain.cases`, :mod:`~promisepatch.domain.steps`,
:mod:`~promisepatch.domain.timers`, :mod:`~promisepatch.domain.inbox` and
:mod:`~promisepatch.domain.outbox` are the **persistence** half: leases, fencing, transaction
boundaries and the audited write boundary. They decide nothing about the workflow; they make a
decision durable, exactly once, or leave the database as it was.

Nothing here implements PromisePatch's exception semantics. The handlers are deliberately
synthetic -- chain, arm a timer, emit a fake effect, fail -- because their job is to exercise
every persistence boundary the real ones will use, not to be them.
"""
