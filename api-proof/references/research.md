# Research basis — 14 October 2026

## Primary-source capabilities

| Tool/standard | Capability | Source |
| --- | --- | --- |
| OpenAPI | Machine-readable HTTP interface descriptions | https://spec.openapis.org/oas/v3.1.2.html |
| Context7 | Current, version-specific docs and examples | https://github.com/upstash/context7 |
| APIs.guru | Community directory of API descriptions | https://github.com/APIs-guru/openapi-directory |
| Postman | Scripted tests, collections and automation | https://learning.postman.com/docs/tests-and-scripts/tests-and-scripts/ |
| Schemathesis | Property-based tests from API schemas | https://schemathesis.readthedocs.io/en/stable/ |
| Pact | Consumer-driven contracts and provider verification | https://docs.pact.io/getting_started/how_pact_works |
| Spectral | JSON/YAML linting and specification rulesets | https://github.com/stoplightio/spectral |

## Design inference

Use these as complementary sources, not proof of complete project fit. APIProof combines project constraints, requirement-level evidence and explicit uncertainty before integration. This review does not establish novelty, exhaustive competitor coverage or market demand. Validate those claims separately.

Require requirements; keep repository context optional for greenfield projects. Separate agent extraction and semantic source assessment from deterministic ledger validation. Ship an agent skill, standard-library verifier and bounded observation helper; defer a web dashboard, marketplace, broad fuzzing and provider-specific adapters.

## Boundary

The earlier “Which Model Is This LLM API Serving?” document concerns hidden model identity. The accepted APIProof MVP concerns API suitability. A successful response, model field or self-report cannot prove hidden model identity. This MVP does not solve that black-box auditing question.

## Acceptance

Exercise all four verdicts, missing evidence, contradictions, freshness, live-proof enforcement, malformed input, artifact tampering and path confinement. Forward-test the skill in fresh agent context. Distinguish actual external probes from offline examples.
