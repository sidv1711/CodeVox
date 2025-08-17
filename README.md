# CodeVox — MVP README

A voice-first **mobile coding assistant** that turns spoken requests into code changes, runs tests, and pings you only when approval is needed.

This doc is both a **dev reference** and an **LLM agent brief**. It defines the product behavior, architecture, APIs, data contracts, and success criteria so humans and agents stay aligned.

---

## 0) TL;DR user experience

- You press one mic button and say what you want: “Add an `--stdin` flag”
- The app uploads a short WAV to the backend
- Backend transcribes the audio → builds an instruction → runs an autonomous code job
- A runner writes the patch, runs lint + tests, and either auto-merges or opens a PR
- You get a push: ✅ merged or ⚠️ approve?
- Nightly we email simple cost/usage totals
- Optional: weekly sprint tag auto-generates an 8-second demo video

Latency target **2–4 s** for simple tasks, typical cloud cost **≈ $0.017/task**

---

## 1) Scope

### In scope (MVP)
- iOS/Android app with one mic screen and a notifications view
- Single-shot **WAV upload** over HTTPS (no streaming)
- **Whisper v3 Turbo** for transcription
- **Anthropic Claude Code** for patch generation
- **Python projects only** (CLI utilities, small FastAPI APIs)
- Lint + test gates: `ruff` + `pytest`
- Heuristic merge rule: auto-merge if **LOC delta < 500** and **no `security/` path touched**
- Push notifications with **Approve / Details**
- **Supabase** for Postgres/Storage/Auth
- **One** EC2 runner (t4g.micro spot) executing a Docker image
- Weekly **Veo** demo clip on tag

### Out of scope (for now)
- On-device wake-word, on-device Whisper, WebSocket streaming
- Risk-engine microservice, vector/RAG memory
- Non-Python stacks
- Production SSO, org admin, payments

---

## 2) Architecture

```mermaid
flowchart TD
    A[Mobile App (React Native + Swift AudioRecorder)] -->|POST /task (JWT + WAV)| B(API Gateway + FastAPI Lambda)
    B -->|Whisper Turbo| C[Transcript]
    B -->|SQS publish| D[SQS runner-jobs]
    E[Runner-0 EC2 t4g.micro] -->|poll| D
    E -->|docker run| F[Claude Code container\n+ ruff + pytest]
    F -->|patch + status| E --> G[GitHub\n(auto-merge or PR)]
    B --> H[Supabase Postgres\nusers, task_events]
    B ---> I[Push notifications (APNS/FCM)]
    G --> J((Weekly tag))
    J --> K[Vertex AI Veo\n8s demo]
    K --> L[Supabase Storage\n(mp4)] --> I
```

### Components

- **Mobile**
  - React Native (Expo) UI
  - Swift `AudioRecorder` using **AVFoundation** → writes `task.wav` → returns file path to RN
  - Expo / FCM push

- **API Edge (Lambda)**
  - FastAPI handlers
  - Supabase JWT verification
  - Whisper Turbo call
  - Build prompt for Claude Code
  - Write `task_events` row (pending)
  - Publish job JSON to SQS

- **Runner-0 (EC2)**
  - Tiny Python agent polls SQS
  - For each job: `git clone` → run Docker image with Claude Code
  - Run `ruff` and `pytest`, collect results
  - If small/safe → commit + push to `main`, else open PR
  - Send compact status back to Lambda callback endpoint

- **Supabase**
  - Postgres: `users`, `task_events`
  - Storage: WAV files (optional), Veo videos
  - Auth: issue JWT for app

- **Veo (optional)**
  - GitHub Action on tag → screenshot staging → Veo → mp4 → push link

---

## 3) Data contracts

### 3.1 SQS job message (JSON)

```json
{
  "job_id": "uuid",
  "user_id": "uuid",
  "repo": "git@github.com:org/project.git",
  "branch": "main",
  "task_text": "Add an --stdin flag so the tool can read from STDIN",
  "style_guide": "PEP8, use argparse, avoid globals",
  "heuristics": { "auto_merge_loc_limit": 500, "blocked_paths": ["security/"] }
}
```

### 3.2 Runner status callback (JSON)

```json
{
  "job_id": "uuid",
  "commit_sha": "abcd1234",
  "pr_url": null,
  "loc_delta": 42,
  "files_touched": ["cli.py", "tests/test_cli.py"],
  "tests_passed": true,
  "lint_passed": true,
  "status": "auto_merged",
  "tok_in": 15000,
  "tok_out": 5000,
  "duration_ms": 2800,
  "notes": "Added --stdin flag, updated docs, 3 tests"
}
```

### 3.3 Postgres tables (Supabase)

```sql
create table if not exists users (
  id uuid primary key,
  email text unique not null,
  provider_choice text default 'claude',
  notify_threshold_loc int default 500,
  created_at timestamptz default now()
);

create table if not exists task_events (
  id uuid primary key,
  user_id uuid references users(id),
  ts_start timestamptz default now(),
  duration_ms int,
  tok_in int,
  tok_out int,
  loc_delta int,
  files_touched jsonb,
  status text check (status in ('ok','fail','auto_merged','pr_opened')),
  notes text
);
```

---

## 4) API surface

### `POST /task`
- **Auth**: Bearer JWT (Supabase)
- **Body**: `multipart/form-data` with `audio` (WAV), optional `repo` override
- **Behavior**:
  - Whisper Turbo → transcript
  - Construct prompt + job JSON → SQS
  - Insert `task_events` pending row
  - Return `202 Accepted` `{ job_id }`

### `POST /callback/runner-status`
- Runner → Lambda
- Updates `task_events`
- Triggers push: ✅ or ⚠️ (with Approve action)

### `POST /webhook/approve`
- Merges PR created for a job (idempotent)

---

## 5) Heuristic decision rule (MVP)

- **Auto-merge** if:
  - `loc_delta < 500`
  - **and** none of `files_touched` start with `security/`
  - **and** `lint_passed` && `tests_passed`
- Otherwise **open PR** and push an approval request

---

## 6) LLM agent brief (how to collaborate)

- **Goal**: Convert user’s natural-language task into minimal, correct Python code changes plus tests
- **Constraints**:
  - Must pass `ruff` and `pytest`
  - Follow repository style (argparse, docstrings)
  - Prefer small diffs that are easy to review
- **Patch etiquette**:
  - Write tests for new behavior
  - Update README/help text when flags change
  - Avoid touching `security/` unless explicitly asked
- **Commit message format**:
  - `feat(cli): add --stdin flag (tests included)`
  - Body: short rationale + test summary

Prompt skeleton the backend will send:

```
Project: <name>
Task: <transcribed text>
Repository map (top-level): <files/dirs>
Style: PEP8, argparse, no globals, ruff + pytest must pass
Deliverables: minimal diff, tests updated, README/help updated when applicable
```

---

## 7) Local dev & test

### 7.1 Mock mode
- Mock Whisper: load fixture transcript from `tests/fixtures/utterance.txt`
- Mock Claude: apply a canned patch in `/mocks/patches/*.diff`
- Toggle via `MVP_MOCK=1`

### 7.2 Unit / integration
- `pytest` for Lambda helpers and runner agent
- Integration: spin a local SQS (e.g., LocalStack) and run one full job with a small sample repo

### 7.3 E2E happy path
1. Launch Runner-0 locally (docker + poller)
2. `curl -F "audio=@sample.wav" -H "Authorization: Bearer <jwt>" https://api/.../task`
3. Verify commit on `main` and push notification log

---

## 8) Deployment plan

### 8.1 Prereqs
- OpenAI Whisper key
- Anthropic Claude key
- Supabase project + service key
- GitHub PAT (`repo` scope)
- Expo/FCM/APNS push credentials

### 8.2 Cloud steps
1. Supabase: create `users`, `task_events`, bucket `media`
2. Build runner Docker image: Claude Code + `ruff` + `pytest` → push to ECR
3. EC2: launch **t4g.micro spot**, install Docker, runner poller
4. SQS: `runner-jobs`
5. API Gateway + Lambda (FastAPI): `/task`, `/callback/runner-status`, `/webhook/approve`
6. Supabase Edge cron: nightly SQL aggregate → email CSV
7. GitHub Action (on tag): screenshot staging → Veo → upload mp4 → notify

### 8.3 Env vars (examples)

```bash
# Lambda
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
PUSH_API_KEY=...   # Expo/FCM/APNS
GITHUB_TOKEN=...

# Runner EC2
GITHUB_TOKEN=...
ECR_IMAGE=...
SQS_URL=...
```

---

## 9) Metrics & SLOs

- **Latency**: p50 voice→merge < 4 s, p95 < 8 s (simple tasks)
- **Success rate**: > 85% tasks auto-merge without human fix
- **Cost**: < $0.03 per task average
- **Error budget**: < 2% Lambda 5xx, Runner job failure rate < 5%

Nightly email includes:
- `sum(tok_in)`, `sum(tok_out)`, `sum(duration_ms)`, `count(*) by status`

---

## 10) Security & secrets

- Least-privilege IAM: Lambda can put to SQS and read Secrets, Runner can get from SQS and pull ECR
- GitHub PAT restricted to target repo(s)
- JWT checked on every `/task`
- Supabase bucket private; signed URLs for media when needed

---

## 11) Roadmap (post-MVP)

- **Latency**: WebSocket streaming + on-device Whisper tiny
- **Throughput**: Runner Auto-Scaling Group / Fargate
- **Safety**: risk engine (OPA + semgrep/bandit), review routing
- **Breadth**: Node/TS support (ESLint + Jest), then Go
- **Observability**: Grafana/Loki dashboards

---

## 12) Glossary

- **Runner**: a small EC2 that executes Claude Code inside Docker and runs tests  
- **Claude Code**: Anthropic’s agentic code editor capable of planning & patching  
- **Whisper Turbo**: fast cloud speech-to-text  
- **Veo**: Google Vertex AI image-to-video model used for 8 s demo clips

---

## 13) Acceptance checklist

- [ ] Talk → transcript → code patch → lint/tests pass  
- [ ] Auto-merge happens for small/safe diffs  
- [ ] PR + push approval for risky diffs  
- [ ] Push notification actions work on device  
- [ ] Nightly cost email received  
- [ ] Weekly tag produces a Veo clip and sends a link

---

### Appendix A — Example `.env` (Lambda)

```dotenv
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
PUSH_API_KEY=...
GITHUB_TOKEN=...
SQS_URL=...
AUTO_MERGE_LOC_LIMIT=500
BLOCKED_PATHS=security/
```

### Appendix B — Example mobile upload

```ts
const form = new FormData()
form.append('audio', {
  uri: fileUri,
  name: 'task.wav',
  type: 'audio/wav',
} as any)

await fetch(`${API_BASE}/task`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${jwt}` },
  body: form,
})
```
