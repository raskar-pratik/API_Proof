# APIProof

**Don't recommend an API. Prove it fits.**

An agent skill for checking HTTP APIs against project requirements before integration. Requirements are mandatory; repository context is optional. It combines provider documentation, optional bounded observations, and a deterministic evidence ledger.

## Use

Copy the `api-proof` folder into an agent skills directory, then ask: “Use APIProof to evaluate APIs for this project.” The agent must have documentation retrieval and, optionally, approved network execution. The standalone scripts require Python 3.10+ and no third-party packages.

```bash
python api-proof/scripts/evaluate.py api-proof/assets/ledger.example.json --output-dir output
python -m unittest discover -s api-proof/scripts -p 'test_*.py' -v
python api-proof/scripts/probe.py examples/github-probe.json --allow-host api.github.com --output output/probe.json
```

The bundled example is synthetic and its fixed observation date will eventually expire. Use current evidence for real decisions. Reports are JSON and Markdown. Verdicts: fit, fit with conditions, not fit, insufficient evidence.

## Scope and limits

Documentation extraction and semantic interpretation remain agent responsibilities. The verifier checks schema, freshness, conflicts, live-artifact bindings and verdict rules. A hash ties recorded bytes to a report; it does not authenticate provider truth. A passing probe does not prove future uptime, pricing, privacy compliance or hidden model identity.

The HTTPS helper uses GET/HEAD only, a host allowlist, public destination checks, verified TLS, no redirects and bounded response bytes. Credentials are read from named environment variables. Confirm an endpoint is harmless; GET does not guarantee no billing or side effects. The creation environment had blocked DNS access. The standalone helper was subsequently verified on a GitHub Actions runner: HTTP 200, JSON parsing, a repository web URL and the expected repository identity all passed. A connected GitHub repository read was also observed successfully and is a different transport.

## Validation

[GitHub Actions verification](https://github.com/raskar-pratik/API_Proof/actions/runs/38541439483): 28 regression tests passed; the standalone HTTPS probe passed all four assertions. This is a bounded observation of one public endpoint, not a load test or uptime guarantee.

## License

MIT; see `LICENSE`.
