# Migrating the Docker Image to a Closed-Network (Azure) Environment

[日本語](SETUP_OFFLINE_DOCKER.md) | **English**

This guide describes how to deploy Digital MATSUMOTO into a closed (air-gapped) Azure environment where `pip`, `git`, and `apt` are unavailable.

## Strategy

All dependency resolution (`pip install` / `apt-get` / `git clone`) is **completed at Docker build time**. Therefore:

> **Build the image in an internet-connected environment, then carry the whole image into the closed network.**

This lets you deploy without ever running `pip` or `git` inside the closed network. There is no need to hand over wheels (`.whl`) or OS packages individually. **The only artifacts to transfer are the image itself, `system.env`, and any required `user/` data — three items.**

> ⚠️ **Important: do NOT re-run `docker build` inside the closed network.** Rebuilding would require network access again. In the closed network, stick to "load and run" only.

### Prerequisites

- The **source** (internet-connected) and **destination** (closed) must use the same CPU architecture (e.g. both `linux/amd64`).
  - If they differ, build explicitly on the source, e.g. `docker build --platform linux/amd64 ...`.
- Docker is already installed on the closed-network VM.
- The Docker image is already built (the starting point of this guide). This document uses the tag `digimatsumoto:offline` as an example.

---

## Step 1. Save the image as a tar and split it by size

Perform this on the source (internet-connected) environment. Split to match the size limit of your transfer path (USB / approved file transfer / Blob, etc.).

```bash
# 1-1. Write the image out as a gzip-compressed tar
docker save digimatsumoto:offline | gzip > digimatsumoto_offline.tar.gz

# 1-2. Split into 2GB chunks (adjust -b to 2000M / 1G / 500M to match your transfer limit)
#      Produces numbered files: digimatsumoto_offline.tar.gz.part-000, ...-001, ...
split -b 2000M -d -a 3 digimatsumoto_offline.tar.gz digimatsumoto_offline.tar.gz.part-

# 1-3. Generate checksums to detect transfer corruption (record both split and joined)
sha256sum digimatsumoto_offline.tar.gz            > digimatsumoto_offline.sha256
sha256sum digimatsumoto_offline.tar.gz.part-*    > digimatsumoto_offline.parts.sha256

ls -lh digimatsumoto_offline.tar.gz.part-*
```

> 💡 `split -d -a 3` produces a 3-digit numeric suffix (`...part-000`, `...part-001`). Dropping `-d` gives alphabetic suffixes (`...part-aa`, `...part-ab`). Ensure the suffix width `-a` is large enough so the join wildcard (Step 3) sorts the parts in order.

Files to transfer:
- `digimatsumoto_offline.tar.gz.part-*` (split image)
- `digimatsumoto_offline.sha256` / `digimatsumoto_offline.parts.sha256` (verification)

---

## Step 2. Transfer to the closed environment

Using your organization's approved path, transfer the files above to a working directory on the closed VM (e.g. `/work/transfer/`).

```bash
# After receipt on the closed VM, verify the split files
cd /work/transfer
sha256sum -c digimatsumoto_offline.parts.sha256
# All entries reporting "OK" means the transfer was lossless
```

> If using Azure as the transit path, routing through a Storage Account (Blob) with a Private Endpoint inside the closed VNet is a safe option. Use `azcopy` / `az storage blob` to exchange files.

---

## Step 3. Reassemble the split files

On the closed VM, join the split files back into the original single tar.gz.

```bash
cd /work/transfer

# 3-1. Concatenate in numeric order (shell wildcard expansion is sorted, so parts join in order)
cat digimatsumoto_offline.tar.gz.part-* > digimatsumoto_offline.tar.gz

# 3-2. Verify the joined file's checksum (matches the value recorded in Step 1-3)
sha256sum -c digimatsumoto_offline.sha256
# "OK" means the join succeeded

# 3-3. Once verified, delete the split files to save disk (optional)
rm -f digimatsumoto_offline.tar.gz.part-*
```

---

## Step 4. Decompress

> `docker load` can read a gzip-compressed tar directly, so explicit decompression is not required.
> Do this only if you want to inspect the intermediate tar, or pass an uncompressed tar to `docker load`.

```bash
# (Optional) Expand the gzip to obtain an uncompressed tar
gunzip -k digimatsumoto_offline.tar.gz   # -k keeps the .tar.gz and produces digimatsumoto_offline.tar
```

---

## Step 5. Load the image and create the container

```bash
# 5-1. Load the image (a compressed tar can be passed as-is)
docker load -i digimatsumoto_offline.tar.gz
#   For an uncompressed tar: docker load -i digimatsumoto_offline.tar

# 5-2. Confirm it loaded
docker images | grep digimatsumoto

# 5-3. (Optional) Verify dependencies are complete with networking fully disabled
docker run --rm --network none digimatsumoto:offline \
  python3 -c "import chromadb, psycopg2, streamlit, MeCab; print('deps OK, no network needed')"
```

Start the container. Ports correspond to the Dockerfile / startup.sh definitions
(8501: main Streamlit, 8895: modified Streamlit, 8899: FastAPI, 8891: spare).

> 💡 **Recommended for first bring-up: start with auto-start OFF.** The Dockerfile's default `CMD` is `startup.sh` (auto-starts all services). On a fresh environment a misconfiguration can make startup fail and Streamlit fall into a Rerun loop, so for the first run pass `-e DIGIM_AUTOSTART=false` to bring the container up **idle**, then `docker exec` in and verify manually. Once it works, switch to normal startup.

```bash
# [Recommended] First run idle, verify manually
docker run -d \
  --name digimatsumoto \
  --restart unless-stopped \
  -p 8501:8501 -p 8895:8895 -p 8899:8899 \
  -v /work/digimatsumoto/user:/app/DigitalMATSUMOTO/user \
  -v /work/digimatsumoto/work:/work \
  --env-file /work/digimatsumoto/system.env \
  -e DIGIM_AUTOSTART=false \
  digimatsumoto:offline

docker exec -it digimatsumoto bash
#   Start services individually inside the container to verify:
#   streamlit run WebDigiMatsuAgent.py --server.port 8501 --server.address 0.0.0.0
#   If it works, run ./startup.sh to start all services

# [Normal operation] auto-start ON (omit DIGIM_AUTOSTART)
docker rm -f digimatsumoto
docker run -d \
  --name digimatsumoto \
  --restart unless-stopped \
  -p 8501:8501 -p 8895:8895 -p 8899:8899 \
  -v /work/digimatsumoto/user:/app/DigitalMATSUMOTO/user \
  -v /work/digimatsumoto/work:/work \
  --env-file /work/digimatsumoto/system.env \
  digimatsumoto:offline

# Check startup logs
docker logs -f digimatsumoto
```

> Prepare `system.env` from `system.env_sample`, pointing it at the closed-network endpoints (Azure OpenAI / PostgreSQL) — see the next step.
> Mounting `user/` as a host volume lets you carry over agent definitions, RAG, and session data across image updates.

### Smoke test

```
http://<closed VM IP>:8501   <- main WebUI
http://<closed VM IP>:8899   <- FastAPI (/run, etc.)
```

---

## Step 6. Switch the agent call function to Azure OpenAI

Inside the closed network you cannot reach public APIs such as `api.openai.com`.
This program **already supports Azure OpenAI Service**, so the following two changes are all that is needed to switch to in-network inference.

### 6-1. `system.env` (environment variables)

Point at an Azure OpenAI resource exposed via a **Private Endpoint** inside the closed VNet.

```bash
# Azure OpenAI core
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<API key>
AZURE_OPENAI_API_VERSION="2024-12-01-preview"

# Move embeddings (RAG) to Azure as well
EMBED_PROVIDER="azure"
AZURE_OPENAI_EMBED_MODEL=<embedding deployment name>

# If you use speech-to-text
TRANSCRIBE_PROVIDER="azure"
AZURE_OPENAI_WHISPER_MODEL=<whisper deployment name>

# tiktoken downloads encoders from a public endpoint, so disable it in a closed network
#   (token counts become approximate, but outbound traffic is eliminated)
TIKTOKEN_DISABLE="true"
#   If you need exact token counts, instead bundle a cache fetched on a connected
#   machine and set TIKTOKEN_CACHE_DIR (see comments in system.env_sample)
```

### 6-2. Agent definition JSON (`FUNC_NAME` and `MODEL`)

Model dispatch is decided by `ENGINE.LLM.<key>.FUNC_NAME` in each agent JSON
(`user/common/agent/agent_*.json`).
Change the public-OpenAI `generate_response_T_gpt` to the **Azure variant `generate_response_T_azure_openai`**,
and replace `MODEL` with the **Azure deployment name**.

```jsonc
// Before (public OpenAI)
"GPT-5.5": {
  "NAME": "GPT-5.5",
  "FUNC_NAME": "generate_response_T_gpt",   // <- calls public OpenAI
  "MODEL": "gpt-5.5",                        // <- OpenAI model name
  ...
}

// After (Azure OpenAI)
"GPT-5.5": {
  "NAME": "GPT-5.5",
  "FUNC_NAME": "generate_response_T_azure_openai",  // <- calls the Azure client
  "MODEL": "<Azure deployment name>",                // <- on Azure, specify the deployment name
  ...
}
```

> **Notes**
> - `generate_response_T_azure_openai` uses `_get_azure_openai_client()` (the `AzureOpenAI` client) and connects via the `AZURE_OPENAI_*` env vars above (see [DigiM_FoundationModel.py](DigiM_FoundationModel.py)).
> - On Azure, `MODEL` is not the OpenAI model name but the **deployment name** you created in the Azure portal.
> - For image generation, similarly replace `generate_image_dalle` with `generate_image_azure_dalle`.
> - Confirm each agent's `ENGINE.LLM.DEFAULT` points at an Azure-enabled key.
> - `FUNC_NAME` values pointing at Gemini / Claude / Grok / Llama are unreachable in a closed network. Use only Azure-based keys.

---

## Note: Web Search (WebSearch)

Internet-based web search is **generally unavailable** in a closed network.

- `WebSearch_OpenAI` uses a plain `OpenAI()` client (`api.openai.com`) plus the Responses API `web_search_preview` tool, and **does not support Azure OpenAI**. Azure OpenAI does not offer an equivalent server-side web-search tool.
- The Perplexity / Google / Claude engines also assume reachability to external APIs, so they do not work in a closed network.

For a closed-network deployment, therefore:

- switch `WEB_SEARCH_DEFAULT` in `setting.yaml` to an operation that does not rely on web search, or do not use web search at all; or
- if strictly required, allow only specific APIs through an approved outbound proxy.

RAG (internal knowledge search) is self-contained via Azure embeddings + local ChromaDB, so it remains usable in a closed network.

---

## Summary (what to provision inside the closed network)

| Item | Detail |
|---|---|
| Application | This image (after `docker load`) |
| LLM inference | Azure OpenAI (Private Endpoint) |
| Embeddings (RAG) | Azure OpenAI Embedding (`EMBED_PROVIDER="azure"`) |
| Vector DB | Bundled ChromaDB (`user/common/rag/chromadb/`) |
| RDB | Azure Database for PostgreSQL (Private Endpoint) — see [SETUP_POSTGRESQL_AZURE.en.md](SETUP_POSTGRESQL_AZURE.en.md) |
| Web search | Disabled by default (no external reachability) |
