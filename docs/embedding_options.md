# Embedding Model/API Options for RAG (section 6a)

Context: `rag/` embeds short, flat chunks — resume bullets, skill entries, cover-letter
paragraphs (see `plan` section 6a, `rag/indexer.py`'s `_experience_entry_to_chunks`).
Scale is personal: a few hundred `DocumentChunk` records per user, re-embedded
occasionally (new resume upload, new generated document) — not a high-volume or
high-QPS workload. This rules out most "scale" concerns (batch throughput, regional
sharding, enterprise SLAs) as decision factors; what actually matters here is
**cost at near-zero volume, number of credentials to manage, and retrieval quality
on short text.**

Per the task constraint: Gemini is documented from official pricing/docs only — no
live call was made against it. AWS Bedrock *was* given a real live test call (see
below) because the AWS credentials already exist in this project (used for S3) and
no new account/credential was created to do it — it returned an account-verification
error, not a credential problem. The local `sentence-transformers` option was
installed and run live end-to-end in an isolated virtualenv (not the project's own
environment, not any other project's environment) with real measured timings and a
confirmed output dimension. Azure OpenAI and Cohere are documented from official
sources only, since testing them live would require creating a brand-new
account/credential, which this research explicitly avoided.

---

## 1. Google Gemini Embeddings (`gemini-embedding-001` / `gemini-embedding-2`)

**Status (Oct 2026):** `text-embedding-004` has been superseded. The current
models are `gemini-embedding-001` (text-only, GA) and `gemini-embedding-2`
(newer, multimodal). The two models' embedding spaces are **incompatible** —
switching models later means re-embedding everything, not a drop-in swap.

- **Cost at this project's scale:** `gemini-embedding-001` is $0.15/1M input
  tokens ($0.075/1M batch); `gemini-embedding-2` is $0.20/1M text input. A
  "few hundred chunks," each maybe 20–40 tokens, re-embedded occasionally, is on
  the order of 10,000–20,000 tokens per full re-embed — **well under $0.01 per
  user per re-embed** either way. Google's docs also describe free-tier access
  for embeddings (rate-limited, tier-dependent — exact RPM/TPM figures are only
  visible in AI Studio's dashboard, which requires a live call to check).
- **New account/credential required:** **No.** This project already has a
  working Gemini API key via `google-genai` (`app/llm.py`). Embeddings are a
  different endpoint on the *same* key — zero new signup, zero new secret to
  store in `.env`.
- **Dimensions:** `gemini-embedding-001` supports Matryoshka Representation
  Learning (MRL) at 768 / 1536 / 3072 dims (recommended sizes). `gemini-embedding-2`
  supports a flexible range from 128–3072, with 768/1536/3072 recommended.
  For a few hundred vectors held in a flat in-memory/JSON store (per
  `DocumentChunk.embedding: list[float]`), dimension size is irrelevant to
  cost or speed — 768 is a sane default (smaller JSON files, trivial to
  store as a plain float list).
- **Latency:** Not measured live (per constraint). Google doesn't publish a
  latency SLA; comparable short-text embedding calls to similar-tier hosted
  APIs (see Cohere/Azure below) typically run 100–400ms per request for single
  short strings. No reason to expect this to be meaningfully different.
- **Quality on short text (resume bullets/skills):** Gemini's embedding models
  are general-purpose, MTEB-competitive text embedding models and handle short
  phrases/sentences well — this is exactly the input shape (single sentences,
  short bullets) they're designed and benchmarked for. No published evidence
  of a short-text weakness.
- **Caveat:** The task constraint explicitly forbids a live Gemini call right
  now (even for embeddings), so this entry is docs-only. Nothing here is a
  reason to avoid it later — it's just not verified empirically today.

---

## 2. Azure OpenAI Embeddings (`text-embedding-3-small` / `text-embedding-3-large`)

Documented only — using this would require creating a **new Azure account and
an Azure OpenAI resource deployment**, which was not done (avoiding unnecessary
new credentials, per the task framing).

- **Cost at this project's scale:** `text-embedding-3-small`: $0.02/1M input
  tokens. `text-embedding-3-large`: $0.13/1M input tokens. At a few hundred
  short chunks (~10–20K tokens per re-embed), this is **fractions of a cent**
  either way — cost is a non-factor at this volume for any provider, Azure
  included.
- **New account/credential required:** **Yes.** Azure OpenAI requires: an
  Azure subscription (billing/credit card on file), explicit resource
  deployment per model/region, and a separate API key + endpoint URL to manage
  alongside the existing Gemini key. This is real overhead: a second cloud
  console, a second credential in `.env`, a second provider's quota/outage
  surface to reason about — for a personal project this is the main cost,
  not the per-token price.
- **Dimensions:** `text-embedding-3-small`: 1536 default (MRL down to 512).
  `text-embedding-3-large`: 3072 default (MRL down to 256). Both support
  8,191-token inputs. Irrelevant at this scale — any of these dimension
  choices store trivially for a few hundred vectors.
- **Latency:** Not tested live (no new Azure resource was provisioned).
  Published community benchmarks for OpenAI's embedding endpoints (Azure uses
  the same underlying models) typically report ~100–300ms for short-text
  single requests, in the same ballpark as other hosted APIs.
- **Quality on short text:** `text-embedding-3-small`/`large` are strong,
  widely-used general embedding models and handle short phrases/sentences
  well; `3-large` has a modest quality edge on retrieval benchmarks (MTEB)
  but at this scale the practical difference on resume-bullet-length text is
  unlikely to be noticeable.
- **Bottom line:** Reasonable models, but there is no quality or cost
  advantage here over Gemini's existing key that would justify standing up a
  second cloud provider/account for a personal-scale project.

---

## 3. AWS Bedrock Titan Embeddings (V2, `amazon.titan-embed-text-v2:0`)

**This one got a real live test call** — the project's existing AWS
credentials (already configured for S3 file storage per the plan, region
`eu-central-1`) were reused; no new AWS account or credential was created.

- **Live test result:** `boto3.client("bedrock-runtime").invoke_model(...)`
  against `amazon.titan-embed-text-v2:0` returned:
  ```
  AccessDeniedException: Your account is currently being verified.
  Verification normally takes less than 2 hours... (aws-verification@amazon.com)
  ```
  This is **not** a Bedrock-specific or credential-setup problem — it's a
  one-time AWS account-level verification gate that's independent of whether
  Bedrock model access has been requested. `list_foundation_models()` *did*
  succeed and confirmed `amazon.titan-embed-text-v1`, `v1:2:8k`, and `v2:0`
  are all listed as `ACTIVE` in this account/region, so once verification
  clears, the call above should work without any further signup.
- **Cost at this project's scale:** ~$0.00002 per 1,000 tokens (Titan
  Embeddings V2) — i.e. $0.02/1M tokens, essentially identical to Azure's
  `text-embedding-3-small`. At a few hundred chunks this is unmeasurably
  cheap (sub-cent per re-embed).
- **New account/credential required:** **Technically no** — this project
  already has an AWS account and working `boto3` credentials for S3. *But*
  Bedrock requires a separate one-time step (requesting/enabling model access
  for Titan Embeddings in the Bedrock console) even on an existing account,
  plus — as hit live above — AWS's account verification gate, which is an
  unpredictable extra delay outside the user's control.
- **Dimensions:** 1,024 (default), or 512/256 — configurable per-request, same
  price regardless. Max input: 8,192 tokens / 50,000 characters.
- **Latency:** Not measured (blocked by the verification gate above) — AWS
  doesn't publish a latency SLA for Bedrock on-demand embedding calls, but
  other Bedrock on-demand model invocations from `eu-central-1` typically run
  in the low hundreds of ms for small inputs.
- **Quality on short text:** Titan Text Embeddings V2 is positioned by AWS for
  retrieval/RAG/semantic-similarity use cases and performs adequately on short
  text, though it's generally regarded (per third-party MTEB-style comparisons)
  as a notch behind OpenAI/Gemini/Cohere's embedding models on English text
  quality — it's "fine," not best-in-class.
- **Bottom line:** Cheapest-per-token alongside Azure small, and *not* a brand
  new credential since the AWS account already exists for S3 — the real
  blocker is the Bedrock console model-access step plus (right now) the
  account verification gate, neither of which is worth navigating when a
  working Gemini key already does the job.

---

## 4. "Hana" — investigation

Best interpretation: **SAP HANA Cloud's vector engine.** SAP HANA Cloud has a
real, documented `VECTOR_EMBEDDING()` SQL function (e.g.
`VECTOR_EMBEDDING('Hello world!', 'DOCUMENT', 'SAP_NEB.20240715')`) plus
`COSINE_SIMILARITY`/`L2DISTANCE` functions for similarity search — so it's not
a mishearing of nothing, HANA genuinely does have embedding capability. But
it's a **database product feature**, not a standalone embedding API: using it
means provisioning a SAP HANA Cloud instance (an enterprise DB service, not a
lightweight API signup) just to get embedding vectors out. For a project
whose entire persistence layer is JSON-files-now/SQLite-later (plan section 1),
pulling in a SAP HANA Cloud instance solely for embeddings would be a wildly
disproportionate new dependency — a new cloud database product, new billing
relationship, new credential, to replace a one-line API call this project
already has via Gemini.

Other plausible mishearings considered but not pursued further (time-boxed,
per the task instructions): OpenAI's older `text-embedding-ada-002` ("Ada") —
plausible phonetically and contextually (it's the other obvious "big
provider's own embedding model" after Azure/AWS were already named), but it's
legacy/superseded by `text-embedding-3-*` so there's no reason to prefer it
over what's already covered in section 2. Hugging Face and Jina AI (both real
embedding-model sources) are less likely matches but are effectively already
covered by the local `sentence-transformers` option below, since Hugging
Face's model hub is exactly where `sentence-transformers` models come from.

**Recommendation:** don't chase this further — whichever it was, it's already
either covered (Hugging Face → section 5) or clearly disproportionate for this
project's scale (SAP HANA Cloud).

---

## 5. Local, free/open-source: `sentence-transformers`

**Live-tested.** Installed `sentence-transformers` (pulls in `torch` and
`transformers`) into an isolated virtualenv (not the project's own
environment, and not any unrelated project's environment) and ran a real
embedding call on resume-bullet-style text locally, no API call, no account,
no internet dependency after the one-time model download.

- **Cost:** **$0.00, always**, at any volume. No per-token, per-request, or
  subscription charge — it's a model running on the local CPU/GPU. The only
  "cost" is local compute (negligible for a few hundred short strings) and
  disk space for the model weights (~80–450MB depending on model size,
  downloaded once from Hugging Face on first use).
- **New account/credential required:** **No.** No signup, no API key, no
  `.env` entry. This is the only option in this comparison with zero
  credentials to manage.
- **Dimensions — confirmed live:** `all-MiniLM-L6-v2` (small, fast, the most
  commonly recommended default for exactly this kind of short-text,
  personal-scale use case) outputs **384 dimensions** (verified by actually
  encoding text and checking `embeddings.shape[1]`). Larger models
  (`all-mpnet-base-v2`) output 768 at higher quality/latency cost. For a few
  hundred chunks, either is trivial to store as a plain JSON float list.
- **Latency — actually measured** (isolated venv, CPU-only, `all-MiniLM-L6-v2`,
  no GPU): one-time model load (includes first-run download from Hugging Face)
  took **24.3s**; after that, encoding **one warm single short sentence took
  ~21ms**, and a batch of 3 mixed resume-bullet/skill/cover-letter-style
  strings took **142ms total**. The 24s load cost is paid once per backend
  process start (not per request) — for a long-running FastAPI process this
  amortizes to nothing; for a serverless/cold-start deployment it would be a
  real latency hit on first request, worth keeping the process warm. Per-chunk
  inference at ~20-50ms with zero network round-trip structurally beats any
  hosted API, which always pays a network hop on top of inference time.
- **Quality on short text:** `all-MiniLM-L6-v2` and similar `sentence-transformers`
  models are explicitly trained/tuned for sentence- and short-phrase-level
  semantic similarity (that's the model family's whole purpose) — a strong
  fit for resume bullets, individual skills, and cover-letter paragraph-level
  chunks. It trails the frontier hosted models (Gemini/OpenAI-3-large) on
  broad MTEB leaderboards, but for *this* project's narrow, personal-corpus
  retrieval task (a few hundred of one person's own chunks, not open-domain
  search), that quality gap is unlikely to be the bottleneck — the bottleneck
  is far more likely to be chunk design and `top_k`/prompt usage than which
  embedding model scored 2 points higher on MTEB.
- **Trade-offs to be upfront about:** adds `torch` + `transformers` as
  dependencies (large install, ~1-2GB with CUDA wheels, smaller CPU-only);
  first-run model download needs internet once; running inference means the
  backend process holds a loaded model in memory (small for MiniLM, but it's
  there) rather than making a stateless HTTP call.

---

## 6. Cohere Embed API (`embed-english-v3.0` / `embed-multilingual-v3.0`)

Documented only — not tested live, since getting an API key means creating a
new Cohere account (even though Cohere's free trial key reportedly doesn't
require a credit card, it's still a new signup/credential to manage, which
this research avoided per the task framing of "don't create new accounts").

- **Cost at this project's scale:** $0.10/1M input tokens. At a few hundred
  short chunks this is still sub-cent per re-embed. Cohere also offers a free
  trial API key with its own rate limits (reported ~100 calls/minute), which
  would cover this project's low-volume, occasional-re-embed usage pattern
  entirely free in practice.
- **New account/credential required:** **Yes** — new Cohere account, new API
  key, new `.env` entry, a third provider to track.
- **Dimensions:** 1,024 default, configurable down to 384 or 768. Max input:
  512 tokens per text (notably smaller than Gemini/Azure/Bedrock's 8K-token
  windows, but irrelevant here since chunks are short bullets/paragraphs, not
  long documents).
- **Latency:** Not tested. Typically reported in the low hundreds of ms for
  short single-text requests, comparable to the other hosted APIs above.
- **Quality on short text:** Cohere's v3 embed models are explicitly
  optimized for retrieval and are strong, well-regarded general-purpose
  embeddings; they handle short text well and are a frequent default choice
  in RAG tutorials for exactly this kind of use case.
- **Bottom line:** A perfectly good model, but offers no concrete quality or
  cost advantage over the Gemini key already in hand — it would only be worth
  the new account if Gemini's embeddings turned out to underperform in
  practice, which there's no evidence of yet.

---

## Recommendation

**Use Gemini's embedding endpoint (`gemini-embedding-001`, 768 dimensions) as
the default for `rag/`'s indexer/retriever**, reusing the API key already
configured in `app/llm.py` / `.env`. At this project's actual scale — a few
hundred chunks per user, re-embedded occasionally — token cost for *every*
option evaluated here is effectively zero (well under a cent per re-embed),
so cost is not a real differentiator. The differentiator that matters is
**how many credentials this project has to manage**, and Gemini is the only
hosted option that requires *zero* new signup, since the key already exists
for `call_llm`. 768 dimensions (not the max 3072) keeps `DocumentChunk.embedding`
JSON records small with no quality cost at this corpus size.

**Second choice, worth keeping in mind but not switching to now: local
`sentence-transformers` (`all-MiniLM-L6-v2`).** It's the only option that is
*structurally* free and credential-free forever, works fully offline, and
was verified live in this research. It becomes the better default the moment
either (a) the "no live Gemini calls" constraint turns out to be long-term
rather than temporary, or (b) there's a wish to avoid *any* per-request network
dependency for retrieval (e.g. to keep `rag/retriever.py` usable even if the
Gemini API has an outage). It costs one extra dependency (`torch`,
`sentence-transformers`) and a local model download, not a new account.

**Not recommended to add right now: Azure OpenAI, AWS Bedrock Titan, Cohere,
or SAP HANA Cloud.** Azure and Cohere both mean a brand-new account/credential
for no measurable quality or cost gain over Gemini at this volume. AWS Bedrock
is the one partial exception — the AWS account already exists for S3 — but it
still needs a separate Bedrock console model-access step and, as the live test
above showed, is currently blocked by an AWS account verification gate outside
the user's control; not worth chasing for a problem Gemini already solves.
SAP HANA Cloud would mean standing up an entire enterprise database product
just to get embeddings, wildly disproportionate to a project whose storage
layer is JSON files.

**If the "no live Gemini calls" restriction is permanent policy rather than
temporary**, swap the recommendation above: make local `sentence-transformers`
the primary choice instead of the secondary one, for the obvious reason that
it's the only option that doesn't call Gemini at all.
