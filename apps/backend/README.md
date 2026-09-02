# promisepatch

The PromisePatch backend. It owns persistence, the audited write boundary, the case engine
and the HTTP surface; every decision that could affect a customer promise is delegated to the
pure `promise_graph` engine.

Run the API locally from the repository root:

```bash
uv run pp api --reload
```

Configuration is read from `PP_`-prefixed environment variables; see `.env.example` at the
repository root for the variables the current code reads.
