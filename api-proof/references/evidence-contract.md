# Evidence contract v1

Use Python 3.10+ with the standard library. Pass a UTF-8 JSON ledger to `evaluate.py`.

```json
{"schema_version":1,"project":"Weather dashboard","max_age_days":30,
 "requirements":[{"id":"R1","text":"Current temperature","required":true,"proof":"live"}],
 "candidates":[{"id":"provider-a","name":"Provider A","evidence":[
   {"requirement_id":"R1","kind":"documentation","outcome":"supports",
    "source":"https://provider.example/docs","excerpt":"Current temperature is returned.",
    "observed_at":"2026-10-14T08:00:00Z","note":"Provider claim; not a live test."}]}]}
```

Require nonempty strings, unique candidate/requirement IDs and explicit booleans. `proof` is `documentation` or `live`; live requirements cannot pass from docs alone. Require at least one must-have. Reject unknown keys to catch misspellings. `max_age_days` defaults to 30 and must be 1–365. Dates must be timezone-aware ISO 8601; future or stale evidence is unusable. Maximum age is a review policy, not a guarantee.

Evidence has `requirement_id`, `kind`, `outcome`, `source`, `observed_at`, optional `note` and `condition`. Documentation requires an `excerpt` and HTTPS source without embedded credentials or query parameters. `outcome` is `supports`, `refutes` or `unknown`. Use `refutes` only for a known constraint failure; outages, 401/403/429 and missing credentials generally mean `unknown` for feature availability.

Live evidence requires `artifact` and `sha256`. Use a relative path beneath the ledger directory. Reject absolute paths, missing files and symlinks outside it. The artifact is `probe.py` JSON output with `schema_version`, `requirement_id`, `url`, `observed_at`, `outcome` and nonempty `checks` of `name` and Boolean `passed`. Ledger and artifact must match requirement, URL, time and outcome. `supports` requires all checks passing; `refutes`/`unknown` requires a failed check. The hash binds a report to recorded bytes, not an authenticated source.

## Aggregation

- Use fresh evidence of the requested proof type; live can satisfy documentation, not vice versa.
- A fresh documentary refutation remains relevant even for a live requirement. A successful request cannot erase a pricing/policy contradiction.
- Usable support plus refutation: `conflict`.
- Refutation alone: `failed`.
- Support alone: `met`; preserve conditions.
- Otherwise: `unknown`; explain missing, stale, future or wrong-type evidence.

Candidate precedence:

1. Failed must-have: `not fit`.
2. Unknown/conflicting must-have: `insufficient evidence`.
3. Must-haves met but optional requirements unmet, conditions present, or a met requirement has documentation only: `fit with conditions`.
4. Otherwise: `fit`.

Bound verdicts to declared requirements and evidence time. Preserve optional failures. Documentation-only suitability needs runtime validation; it never receives an unqualified `fit`.

## Probe specification

```json
{"requirement_id":"R1","url":"https://api.provider.example/v1/weather?city=Pune",
 "method":"GET","headers_env":{"Authorization":"PROVIDER_AUTH"},"expect_status":200,
 "json_equals":{"/units":"celsius"},"json_present":["/temperature"],"failure_outcome":"unknown"}
```

Run `python3 scripts/probe.py SPEC --allow-host api.provider.example --output probe.json`.
Set environment values outside the command. Header environment values contain the whole value, e.g. `Bearer …`. Avoid secrets in queries; common credential parameter names are rejected. HEAD cannot assert JSON. The helper follows no redirects, rejects nonpublic addresses, connects to a checked IP with hostname/TLS verification, disables proxy inheritance, caps response bytes at 1 MiB, uses a 10-second socket timeout and sends one request without retries. These bounds do not guarantee zero cost. Output stores check results and response metadata/hash, not response body or credential headers. Failed expectations default to `unknown`; choose `refutes` only for a meaningful feature assertion.
