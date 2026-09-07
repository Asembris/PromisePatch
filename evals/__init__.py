"""Measurement, kept outside the thing it measures.

PromisePatch's semantic layer proposes; deterministic code authorizes. This package answers
one question about that arrangement -- *can we measure how well the proposing half does its
job* -- and it answers it without being able to change anything.

Three properties are structural rather than stated:

* **Nothing production imports this.** An import-linter contract forbids `promisepatch`,
  `promise_graph`, `order_contract` and `order_simulator` from reaching anything here or the
  evaluation framework behind it. Measurement that could change the measured system is not
  measurement.
* **This cannot reach a model, a database or the network.** A second contract forbids the AWS
  SDK, SQLAlchemy, Alembic, the HTTP clients and `promisepatch.integrations` from being
  imported here. The offline runner answers every case from a scripted payload through the
  production fake, so an evaluation run cannot spend money by accident.
* **Gold data cannot reach a prompt.** A gold case becomes a
  :class:`~evals.cases.ModelInput` before anything is asked of a provider, and that projection
  carries the request and nothing else. Tests assert the absence rather than trusting it.

The dataset, the labels, the metric definitions, the thresholds and the risk policy belong to
PromisePatch. DeepEval is a runner: it executes cases and reports, and it decides nothing.
"""
