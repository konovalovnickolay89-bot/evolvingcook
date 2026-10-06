# Decision D10 — LLM provider for catalogue ingest

| Field | Value |
|-------|--------|
| Decision | **Mistral**, not Anthropic |
| Key env | `MISTRAL_API_KEY` (EnvironmentFile / `.env` only; never commit) |
| Model env | `LLM_MODEL` (default **`mistral-medium-latest`** — **multi-modal / vision** for sheet photos, including rotated; replaces retired `pixtral-large-latest`) |
| Token cap | `LLM_MAX_TOKENS` (default **32768** — dense MEP grids truncated at 8192) |
| Transport | `httpx` → `https://api.mistral.ai/v1/chat/completions` (OpenAI-compatible; **no SDK**) |
| Multi-modal | User message = text block + one-or-more `image_url` data-URLs (`data:image/jpeg;base64,…`). Photo-only uploads allowed. |
| Module | `catalog/llm_provider.py` — thin provider; swap = env + this file |
| Response | `response_format: {"type":"json_object"}` |
| Domain writes | **Never.** LLM → review/proposal rows only; accept handler validates Item + SupplierItem |

Blocked env name for live ingest: **`MISTRAL_API_KEY`** (not `ANTHROPIC_API_KEY`).

Photo ingest requires a vision model (default `mistral-medium-latest`). Plain text-only models raise a clear error if an image is attached.

Phase 5 **assist** (recipes, demand proposals, verbs) is **not** this path — see **D11** `docs/D11-HERMES-A2A-ASSIST.md` (Hermes A2A + signed push → `AssistProposal`).
