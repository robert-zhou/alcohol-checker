# Approach, Tools, and Assumptions

> **Want to try the deployed service instead of running it yourself?** It's live at
> [https://alcver-app-robert.azurewebsites.net/](https://alcver-app-robert.azurewebsites.net/) — email
> [robertzhongzhou@gmail.com](mailto:robertzhongzhou@gmail.com) to request login credentials.

This document summarizes the design decisions behind the prototype and how they map back to the
discovery notes from the Compliance Division interviews.

## Problem summary

TTB agents currently compare label applications to label artwork by eye: brand name, ABV, net
contents, and the government warning statement all have to match what's on file. Most of this is
routine matching, not judgment, and it consumes a large share of a 47-person team's day across
~150,000 applications/year. A prior scanning-vendor pilot failed on latency (30-40s/label) and was
abandoned. Any new tool needs to be fast, very easy to use for a team with a wide range of tech
comfort, support bulk uploads for peak-season importers, and leave room for human judgment on
edge cases rather than blind rejection.

## Approach

- **Vision LLM extraction instead of OCR + regex.** A single call to a vision-capable LLM
  ([app/integrations/llm.py](app/integrations/llm.py)) reads the label image directly and returns
  structured JSON for each required field, plus a small set of visual attributes (case-exactness
  and boldness for the government warning). This avoids building and tuning a traditional
  OCR/parsing pipeline, and keeps typical end-to-end latency to roughly 4-6 seconds per label —
  well under the "5 seconds or agents won't use it" bar Sarah described, and far below the 30-40s
  scanning-vendor pilot that failed.
- **Structured, size-bounded output.** The extraction schema is intentionally narrow — only the
  fields actually used in comparisons, with a length cap on free-text notes. This keeps prompts
  and responses small (faster, cheaper) rather than asking the model for an exhaustive attribute
  set that the app doesn't use.
- **Tolerant matching, not exact string equality, for most fields.** Field comparison
  ([app/domain/label_utils.py](app/domain/label_utils.py)) uses fuzzy string similarity for text
  fields and unit-aware numeric comparison for ABV/net contents (e.g. `750 mL` vs `0.75 L`).
  This directly addresses Dave's "STONE'S THROW" vs "Stone's Throw" example — a formatting
  difference doesn't get flagged as a hard mismatch.
- **Zero tolerance specifically for the government warning.** Per Jenny's note, the warning
  statement is checked for exact wording, an all-caps "GOVERNMENT WARNING:" lead-in, and a
  boldness signal ([app/domain/format_validator.py](app/domain/format_validator.py)) — this field
  intentionally has no fuzzy-match leniency, unlike the others.
- **Three-way outcome instead of binary pass/fail.** Every field and every case resolves to
  `pass`, `need_review`, or `failure` rather than an automatic accept/reject. This preserves the
  human judgment Dave asked for — borderline cases are routed to a reviewer instead of being
  silently auto-approved or auto-rejected.
- **Human review is a first-class workflow, not an afterthought.** Reviewers can record a
  decision, a comment, and an override value per field, and set a final case decision
  ([app/infrastructure/db.py](app/infrastructure/db.py)); all of this is persisted, which is
  useful for defensibility of overturns and audit.
- **Batch upload with async job polling.** `/api/batch` accepts many application/label pairs at
  once and processes them as a background job the browser can poll
  ([app/services/batch_service.py](app/services/batch_service.py)), so a 200-300 label dump from
  an importer doesn't require one-at-a-time submission or block the browser tab.
- **Deliberately plain, single-page UI.** One page, large obvious buttons, no nested menus or
  configuration screens — aimed at the full range of tech comfort described (Dave through Jenny),
  per Sarah's "my mother could figure it out" bar.
- **Lightweight guardrails around the paid LLM dependency.** An optional login gate, an optional
  shared API key, and a per-client rate limiter ([app/services/rate_limiter.py](app/services/rate_limiter.py))
  protect the vision-model endpoint from open/excessive use without introducing a full identity
  provider for a prototype. See "Why a login gate and rate limiter, even for a prototype" below
  for the reasoning.

### Why a login gate and rate limiter, even for a prototype

Marcus's guidance was "just don't do anything crazy" for the prototype, and that no sensitive data
is being stored — which is true and is why this app has no Key Vault, no identity provider, and no
compliance-grade audit hardening. But an unauthenticated web app is a different risk category from
an unauthenticated data store, for reasons specific to this design:

- **Every verify call spends real money.** Each `/api/verify` request makes a paid vision-LLM API
  call. Deploying this to a public `*.azurewebsites.net` URL with no gate at all means anyone who
  finds or guesses the URL — not just TTB staff — can run up the API bill indefinitely, or exhaust
  a rate-limited/quota-limited model deployment that agents actually need. This isn't a
  data-confidentiality concern, it's an availability/cost concern, but it's just as real for a
  prototype that's meant to demonstrate a working tool, not accidentally rack up API spend
  overnight.
- **The scanning-vendor pilot failure mode was a latency/availability problem, not a security one**
  — but the lesson generalizes: if the tool becomes slow or unavailable because of unrelated
  traffic (or a scraper, or a stress-test, or simple accidental repeated submissions), agents will
  abandon it exactly like they abandoned the 30-40s pilot. The per-client rate limiter
  ([app/services/rate_limiter.py](app/services/rate_limiter.py)) protects the 5-second experience
  Sarah needs, not just the budget.
- **The cost is proportionate to the requirement.** Both controls are a username/password check
  against two environment variables and an in-memory sliding-window counter — no database schema,
  no external service, no session-store infrastructure beyond a signed cookie. This is deliberately
  the minimum that closes the "public internet can spend our money and degrade the demo" gap
  without contradicting Marcus's "don't overbuild" guidance. Both are also fully optional
  (`AUTH_USERNAME`/`AUTH_PASSWORD` empty disables login; rate limits set to `0` disable limiting),
  so the prototype can still be run wide open for a quick local demo if that's ever preferred.
- **It's the cheapest possible insurance against scope creep.** If this prototype does inform a
  future procurement decision (as Marcus suggested it might), having already exercised basic
  access control and abuse protection — however lightweight — means that transition doesn't start
  from zero. Retrofitting auth onto an app that's been open by default is more disruptive than
  keeping a toggle that was there from day one.

## Requirements traceability

This section checks the implementation directly against the discovery-note requirements, so the
design choices above can be justified item by item rather than taken on faith.

| Requirement | Source | Implementation | Justification |
| --- | --- | --- | --- |
| Results back in ~5 seconds or agents won't use it | Sarah (scanning-vendor pilot took 30-40s and was abandoned) | Single vision-LLM call per label, narrow structured output schema, no OCR pipeline ([app/integrations/llm.py](app/integrations/llm.py)) | Measured end-to-end latency of ~4-6s per case in testing — under the 5s bar, and an order of magnitude faster than the pilot that failed for this exact reason |
| Usable by staff across the full tech-comfort spectrum ("my mother could figure it out") | Sarah | One static page, two tabs (single/batch), no configuration screens, plain upload → result flow ([app/static/index.html](app/static/index.html)) | No login/nav hunting; the whole workflow is upload → wait → read result, matching the simplicity bar described |
| Handle bulk uploads (200-300 applications) from importers during peak season | Sarah / Janet | `/api/batch` accepts many application/label pairs plus a mapping file and runs them as one background job, polled from the browser ([app/services/batch_service.py](app/services/batch_service.py)) | Removes the one-at-a-time submission bottleneck Sarah described; a batch runs without blocking the browser tab |
| Judgment matters — don't hard-fail on cosmetic differences (e.g., "STONE'S THROW" vs "Stone's Throw") | Dave | Fuzzy string similarity for text fields, unit-aware numeric comparison for ABV/net contents, three-way `pass` / `need_review` / `failure` outcome instead of binary accept/reject ([app/domain/label_utils.py](app/domain/label_utils.py)) | Cosmetic formatting differences resolve to `pass`/`suspect` rather than an automatic hard failure; genuinely ambiguous cases route to `need_review` for a human rather than being auto-decided either way |
| Don't make agents' lives harder / don't add friction to their existing queue work | Dave | Every field-level result includes a plain-language reason; manual override with a comment is one click away, all changes are logged ([app/infrastructure/db.py](app/infrastructure/db.py)) | Agents aren't asked to re-derive why something was flagged, and overriding a wrong call is fast and auditable rather than fighting the tool |
| Government warning must be checked **exactly** — wording, all-caps "GOVERNMENT WARNING:", bold | Jenny | Dedicated exact-match + formatting checks with no fuzzy leniency, plus visual case-exactness/boldness signals from the vision model ([app/domain/format_validator.py](app/domain/format_validator.py)) | This is the one field explicitly called out as needing zero tolerance; it's the only field in the schema with its own attribute checks rather than reusing the generic fuzzy-match path |
| Handle labels that aren't shot perfectly (angle, lighting, glare) | Jenny (flagged as possibly out of scope) | Vision-LLM extraction instead of traditional OCR, which tends to be materially more robust to real-world photo conditions; no dedicated deskew/preprocessing pipeline was built | Treated as a "best-effort, not guaranteed" capability per the Assumptions section below — genuinely unreadable labels still resolve to low-confidence/`need_review` rather than a silent bad read, preserving the existing "ask for a better image" fallback Jenny described |
| Standalone prototype, no COLA integration or its auth requirements | Marcus | Application data is uploaded directly (JSON/PDF/text upload) rather than pulled from COLA; no COLA API client exists in the codebase | Matches the explicit scope boundary — this app never assumes COLA credentials, session state, or data access |
| Outbound network to ML/cloud endpoints may be blocked by firewall (as it was for the scanning-vendor pilot) | Marcus | LLM endpoint is fully configurable via `OPENAI_BASE_URL`/`OPENAI_API_KEY` ([app/config.py](app/config.py)); not hardcoded to a specific vendor domain | Documented as a risk to confirm with IT before rollout (see Assumptions) rather than silently assumed away, since this exact failure mode already broke a prior pilot |
| Prototype-level security is fine; no PII/production compliance requirements needed yet | Marcus | Optional login gate, optional shared API key, per-client rate limiting on LLM-backed endpoints ([app/services/rate_limiter.py](app/services/rate_limiter.py)); secrets via App Service application settings, not a full secrets vault | Not about data confidentiality — about protecting a paid, rate-limited LLM endpoint from unrestricted public access so cost and the 5-second experience aren't put at risk; see "Why a login gate and rate limiter, even for a prototype" above for the full reasoning |
| Free choice of language/framework/libraries | Technical requirements | Python/FastAPI backend, vanilla JS frontend, MySQL storage | Chosen for fast iteration and minimal ceremony appropriate to a prototype, not dictated by any stated constraint |
| Label must contain brand, class/type, alcohol content, net contents, bottler/producer name+address, country of origin (imports), government warning | TTB label requirements / sample label | All seven fields are part of the extraction schema and comparison logic ([app/integrations/llm.py](app/integrations/llm.py), [app/domain/label_utils.py](app/domain/label_utils.py)) | Directly covers the fields called out in both the technical requirements and the sample label example |
| Existing infrastructure is on Azure (COLA migrated to Azure in 2019) | Marcus | Prototype is deployed on Azure App Service (Linux container) + Azure Database for MySQL Flexible Server, using the same Azure AD tenant/subscription model as the rest of TTB's environment | Deploying on the same cloud platform TTB already operates on means no new vendor relationship, no new network-egress/firewall exception beyond what's already been evaluated for Azure traffic, and no separate compliance/security review process to stand up — directly reducing both cost (single provider, existing enterprise agreement) and security review overhead compared to introducing a second cloud vendor for a prototype |

## Tools and stack

- **FastAPI** — backend framework; async, minimal boilerplate, good fit for a small prototype.
- **OpenAI SDK against an Azure AI Foundry vision deployment** (`gpt-4.1-mini`) — used purely as
  an OpenAI-compatible client; any OpenAI-compatible vision endpoint can be swapped in via config.
- **Vanilla JS/CSS static frontend** — no build step, no framework, easiest to hand off/maintain
  for a small internal tool.
- **MySQL** (`mysql-connector-python`, pure-Python driver) — stores verification results, reviewer
  decisions, and audit timestamps. Schema is created and upgraded automatically at startup, so no
  manual migration step is needed when standing up a fresh database.
- **pypdf / Pillow** — parsing PDF application payloads and handling uploaded label images.
- **Docker + Azure App Service (Linux container) + Azure Database for MySQL Flexible Server** —
  deployment target for a single-instance prototype (see [README.md](README.md)). Azure was
  chosen specifically because TTB's existing infrastructure (including COLA) already runs on
  Azure per Marcus — staying on the same cloud provider avoids introducing a second vendor's
  security review, network-egress allowlist, and procurement process just for this prototype,
  which lowers both cost and security overhead relative to standing up infrastructure on an
  unrelated platform. This is also explicitly why AWS, GCP, or any other cloud provider was not
  considered: introducing a second cloud vendor would mean a separate FedRAMP/security
  authorization path, a separate set of firewall/network-egress exceptions to negotiate with
  Marcus's team, and a separate billing/procurement relationship — none of which buys anything
  for a prototype whose only cloud dependency is a container host, a small MySQL instance, and an
  outbound call to a vision-LLM endpoint, all of which Azure already provides natively.
- **pytest** — automated tests against sample application/label fixtures in
  [sample_cases](sample_cases).

## Assumptions

### Input format assumptions

Each case is assumed to be **one application record paired with one label photo**:

- **Application record** — a single TTB label application, provided as a PDF, a JSON object, or
  plain text. PDF is the expected format for a real submission (see
  [sample_cases/example_application.pdf](sample_cases/example_application.pdf) and
  [sample_cases/clean_ocr_case/application.json](sample_cases/clean_ocr_case/application.json) for
  the JSON shape the app expects once parsed — `brand`, `class`, `abv`, `net_contents`,
  `government_warning_present`, `producer_name`, `country_of_origin`). The app assumes the PDF is
  text-based (not a scanned image of text) so it can be parsed directly; a scanned/flattened PDF
  application is not handled by a separate OCR step.
- **Label photo** — a single image (PNG/JPEG) of one bottle's label, assumed to show the front
  and/or back label content needed to read all seven fields in one shot. See
  [sample_cases/clean_ocr_case/label.png](sample_cases/clean_ocr_case/label.png) and
  [sample_cases/mismatch_case/label.png](sample_cases/mismatch_case/label.png) for the two
  reference examples used in tests — one where the label matches its application, and one with an
  intentional mismatch. Multiple photos of the same bottle (e.g., separate front/back shots) are
  not supported per case in this prototype; a single photo is assumed to be legible enough to
  cover the required fields, consistent with how agents currently review one label image per
  application.
- **One-to-one pairing.** A single case is exactly one application to one label. The batch
  workflow is this same 1:1 assumption repeated N times: N application files, N label files, and a
  mapping file that explicitly pairs each application to its label by filename — see
  [sample_cases/batch_fixture](sample_cases/batch_fixture) for a full worked example (10
  applications, 10 labels, and [mapping.json](sample_cases/batch_fixture/mapping.json) pairing
  them). The app does not attempt to guess pairings from filename similarity beyond what the
  mapping file specifies; an unmapped file is treated as an error rather than a best-effort guess.

### Other assumptions

- **Standalone proof-of-concept, not integrated with COLA.** Per Marcus, this app does not touch
  the production COLA system or its authorization requirements; it takes application data as
  JSON/PDF/text uploaded independently.
- **No production-grade secret management.** Because this is a single-instance prototype, secrets
  are stored as platform-encrypted App Service application settings rather than a dedicated
  secrets vault. This assumption should be revisited before any wider or multi-instance rollout.
  No PII or sensitive production data is stored — only prototype/demo label and application data.
- **Outbound network access to the LLM endpoint is available.** Marcus flagged that outbound
  traffic to ML vendor endpoints was blocked during the earlier scanning-vendor pilot. This
  prototype assumes the chosen vision-model endpoint's domain would be added to an allowlist; this
  is called out here as a risk to confirm with IT before any production rollout, not something
  solved by the prototype itself.
- **Core label fields only.** The prototype validates the common cross-category fields (brand,
  class/type, ABV, net contents, producer/address, country of origin, government warning).
  Beverage-type-specific exceptions (e.g., ABV disclosure exemptions for certain wine/beer
  categories) are out of scope.
- **Standard government warning wording.** The exact-match check assumes the standard federally
  mandated warning text and formatting; it does not attempt to enumerate every historically
  approved alternate wording.
- **Image quality is handled best-effort, not guaranteed.** Off-angle photos or glare (Jenny's
  note) are expected to work reasonably well because vision LLMs are comparatively robust to this
  compared to traditional OCR, but there's no dedicated image-preprocessing/deskewing pipeline in
  this prototype — a label that's genuinely unreadable will still come back as low-confidence/
  needs-review rather than being auto-corrected.
- **Representative, not exhaustive, test data.** Test fixtures use a handful of synthetic/sample
  labels (clean cases and a few edge cases) rather than a full corpus covering every TTB label
  variant, consistent with this being a prototype rather than a certified production system.
- **Single-instance scale.** Rate limiting and batch-job state are kept in-process (in memory),
  which is sufficient for one app instance but would need externalizing (e.g., shared cache) if
  scaled to multiple instances later.

## Future work

Comparing the current implementation against the discovery-note requirements surfaces a few gaps
that are reasonable to defer for a prototype but should be addressed before any wider rollout:

- **Multi-photo labels (front + back).** Jenny noted some labels split required fields across
  front and back images; today the app only accepts one photo per case, so a label that needs two
  shots to cover all seven fields isn't fully supported. Adding multi-image upload per case, with
  the vision-LLM call reading both images together, would close this gap.
- **Image preprocessing for poor-quality photos.** Off-angle shots and glare are currently handled
  only as well as the vision model handles them natively — there's no deskew/glare-correction
  step. A dedicated preprocessing pass (or a "retake photo" quality check before submission) would
  make the tool more robust for agents photographing labels in the field, not just clean sample
  images.
- **COLA integration.** The prototype deliberately takes application data as a standalone
  upload rather than pulling it from COLA (per Marcus's explicit scope boundary). If this
  prototype informs a real procurement decision, integrating directly with COLA to fetch
  application data (instead of requiring a separate PDF/JSON upload) would remove a manual step
  agents currently have to do themselves.
- **Production-grade secrets management.** Secrets currently live in App Service application
  settings rather than a dedicated vault (e.g., Azure Key Vault). This was an explicit
  prototype-scope tradeoff since no PII/sensitive data is involved yet, but a production rollout
  should move secrets into Key Vault with managed-identity access, consistent with how the rest
  of this deployment already uses managed identity for ACR.
- **TTB-managed authentication instead of a shared login/password.** The current login gate is a
  single shared username/password pair, adequate for a prototype but not for per-agent
  accountability. A production version should integrate with TTB's existing identity provider
  (Azure AD, given TTB's infrastructure is already on Azure) so overrides and audit entries are
  tied to an individual agent's identity rather than a shared credential.
- **Multi-instance / horizontal scaling.** Rate-limiter state and batch-job state are in-process
  only. Scaling beyond a single App Service instance would require externalizing this state (e.g.,
  Redis or a shared table) so limits and job status stay consistent across instances.
- **Beverage-type-specific validation rules.** Only the common cross-category fields are checked
  today; category-specific exceptions (e.g., ABV disclosure exemptions for certain wine/beer
  categories) are out of scope and would need dedicated rule sets per beverage type.
- **Broader government-warning wording coverage.** The exact-match check assumes the current
  standard federal warning text; it doesn't enumerate historically approved alternate wordings,
  which would need to be added if those are still in active use.
- **Confirming outbound network access with IT.** The earlier scanning-vendor pilot failed partly
  because outbound traffic to an ML vendor endpoint was blocked. This prototype assumes the
  vision-model endpoint's domain can be allowlisted, but that hasn't been confirmed with IT — this
  should happen before any production deployment.
- **Larger, more representative test corpus.** Current fixtures cover a handful of
  synthetic/sample cases rather than the full variety of real label formats and edge cases TTB
  agents see; expanding this would increase confidence ahead of a wider rollout.
- **CI/CD pipeline.** Builds and deploys are currently run manually via the Azure CLI steps in
  [README.md](README.md). A GitHub Actions workflow to build, test, and deploy on merge would
  reduce manual deployment risk and make the process easier to hand off.
