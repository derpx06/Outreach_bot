# Xenia26 Agent Architecture Map

This document is code-accurate to the current implementation in:
- `fastapi/ml/routes.py`
- `fastapi/ml/application/agent/graph.py`
- `fastapi/ml/application/sarge/graph.py`
- `fastapi/ml/ollama_deep_researcher/graph.py`

## 1. System Architecture Map

```mermaid
flowchart LR
    U[User]
    FE[Frontend React/Vite]
    BE[Node/Express API :8080]
    FA[FastAPI ML API :8000]
    OLL[Ollama Local LLM]
    HF[Hugging Face / Model Cache]
    WEB[Web Search + Crawlers]
    SQL[(SQLite database.db)]
    SMEM[(SQLite sarge_memory.db)]
    KB[(JSON + Chroma Knowledge Base)]
    VP[(assets/voice_profiles)]
    SA[(static/audio)]

    U --> FE
    FE -->|Auth, contacts, send| BE
    FE -->|Chat + SSE + TTS| FA

    FA -->|/ml/agent/*| SQL
    FA -->|SARGE memory| SMEM
    FA -->|Retriever/KB| KB
    FA -->|Voice profiles| VP
    FA -->|Generated WAV| SA

    FA --> OLL
    FA --> WEB
    FA --> HF
```

## 2. Route-to-Agent Map

```mermaid
flowchart TD
    R[FastAPI /ml Router]

    A1["POST /ml/agent/chat (SSE)"]
    A2["POST /ml/agent/chat-sync"]
    W1["POST /ml/agent/writer/chat (SSE)"]
    S1["POST /ml/agent/sarge/chat (SSE)"]
    S2["POST /ml/agent/sarge/chat-sync"]
    V1["GET /ml/agent/sarge/voices"]
    V2["POST /ml/agent/sarge/voice-profile"]
    V3["POST /ml/agent/sarge/voice"]
    T1["GET /ml/agent/threads"]
    T2["GET /ml/agent/threads/{thread_id}"]

    G1[Research Outreach Agent Graph]
    G2[Digital Newsroom Graph]
    G3[SARGE Graph]
    TTS[Qwen3-TTS 0.6B Engine]

    R --> A1 --> G1
    R --> A2 --> G1
    R --> W1 --> G2
    R --> S1 --> G3
    R --> S2 --> G3

    R --> V1 --> TTS
    R --> V2 --> TTS
    R --> V3 --> TTS

    R --> T1
    R --> T2
```

## 3. Agent Graph A: Research Outreach Agent (`ml/application/agent`)

### Runtime behavior
- Entry point: `intent_router`.
- Direct bypass for `small_talk` and `system_question`.
- Supervisor-driven loop for heavy outreach generation.
- `parallel_analysis` runs `profiler` + `strategist` concurrently.

```mermaid
flowchart TD
    START([START]) --> IR[intent_router]

    IR -->|small_talk or system_question| DR[direct_response]
    DR --> END([END])

    IR -->|otherwise| MC[mention_context]
    MC --> SUP[supervisor]

    SUP -->|next_step=hunter| H[hunter]
    SUP -->|next_step=profiler| P[profiler]
    SUP -->|next_step=strategist| ST[strategist]
    SUP -->|next_step=parallel_analysis| PA[parallel_analysis]
    SUP -->|next_step=scribe| SC[scribe]
    SUP -->|next_step=critic| CR[critic]
    SUP -->|next_step=end| END

    H -->|prospect found| PA
    H -->|no prospect| SUP

    PA --> SUP
    P --> SUP
    ST --> SUP
    SC --> SUP
    CR --> SUP
```

## 4. Agent Graph B: SARGE (`ml/application/sarge`)

### Runtime behavior
- Entry point: `router`.
- Low-confidence intent routes to `clarification`.
- `generate` and `refine` both pass through `style_inferrer`.
- Critic loop retries writer up to 2 attempts.
- Voice synthesis is the terminal stage for chat/generation/edit flows.

```mermaid
flowchart TD
    START([START]) --> R[router]

    R -->|confidence < 40| CL[clarification]
    CL --> END([END])

    R -->|chat| C[chat]
    C --> V[voice]
    V --> END

    R -->|unknown| FB[fallback]
    FB --> END

    R -->|generate| SI[style_inferrer]
    R -->|refine| SI

    SI -->|router_decision=refine| E[editor]
    E --> V

    SI -->|router_decision=generate| P[profiler]
    P --> RET[retriever]
    RET --> W[writer]
    W --> CR[critic]

    CR -->|retry| W
    CR -->|end| V
```

### TTS sub-architecture used by SARGE

```mermaid
flowchart LR
    TXT[Input Text] --> CLEAN[Strip headers / Subject / To / CC]
    CLEAN --> PICK[Resolve voice mode + profile]
    PICK --> PROMPT[Ensure clone prompt]
    PROMPT --> QWEN[Qwen3-TTS-12Hz-0.6B-Base]
    QWEN --> WAV[Write WAV to static/audio]
    WAV --> URL[/static/audio/...]
```

## 5. Agent Graph C: Digital Newsroom (`ml/ollama_deep_researcher`)

### Runtime behavior
- Entry point: `orchestrator`.
- Loops `research_worker -> writer` per planned section.
- Publishes only when `current_section_index >= len(outline)`.

```mermaid
flowchart TD
    START([START]) --> O[orchestrator]
    O --> P[planner]
    P --> RW[research_worker]
    RW --> W[writer]
    W -->|more sections| RW
    W -->|all sections done| PUB[publisher]
    PUB --> END([END])
```

## 6. State and Storage Map

| Area | Storage | Purpose |
|---|---|---|
| Thread history | `database.db` | `/ml/agent/chat*` + writer thread persistence |
| SARGE memory | `fastapi/ml/application/sarge/sarge_memory.db` | Session-level short history for SARGE |
| Voice profiles | `assets/voice_profiles/` + `profiles.json` | Uploaded clone references and defaults |
| Generated audio | `static/audio/` | WAV files returned to frontend |
| Knowledge base | `ml/application/agent/data/` | Prospect JSON, psych JSON, Chroma vector history |

## 7. Key Integration Notes

- Agent modules are lazy-loaded from `ml/routes.py` (`_ensure_agent_loaded`, `_ensure_sarge_loaded`, `_ensure_deep_research_loaded`) to keep startup resilient.
- TTS is lazy-loaded independently (`_load_tts_or_503`) so SARGE text flows can still run if voice dependencies fail.
- Subject/header stripping for TTS happens before synthesis (`_extract_tts_body_text`), so spoken audio is body-focused instead of reading email headers.
