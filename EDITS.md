# Modifiche rispetto alla baseline

Tutte le modifiche apportate rispetto al codice/configurazione originale del repository.

---

## `.env`

| Campo | Prima | Dopo |
|---|---|---|
| `GRAPHRAG_API_BASE` | `https://openwebui.nicolfo.it/v1` | `https://openwebui.nicolfo.it/api` |

**Perché:** OpenWebUI espone la sua API compatibile OpenAI sotto `/api`, non `/v1`. Il path corretto per chat completions diventa `/api/v1/chat/completions` (l'SDK OpenAI appende `/v1/...` automaticamente).

---

## `settings.yaml`

### Completion model — aggiunto `call_args`
```yaml
call_args:
  extra_headers:
    User-Agent: python-httpx/0.27.0
```
**Perché:** OpenWebUI blocca le richieste con `User-Agent: OpenAI/Python x.x.x` restituendo HTTP 403. L'override dell'header bypassa il blocco.

### Embedding model — aggiunto `call_args`
```yaml
call_args:
  extra_headers:
    User-Agent: python-httpx/0.27.0
  encoding_format: "float"
```
**Perché:** vLLM rifiuta `encoding_format: null` (valore di default di litellm). L'impostazione esplicita a `"float"` risolve il 400 Bad Request.

### Vector store — dimensione vettore corretta
```yaml
vector_size: 2560   # era 1536
```
**Perché:** `Qwen/Qwen3-Embedding-4B` produce vettori a 2560 dimensioni, non 1536 (OpenAI ada-002). LanceDB falliva con `The length of the values Array needs to be a multiple of the list_size`.

---

## `settings.auto.yaml`

### Completion model — aggiunto `model_provider`
```yaml
model_provider: openai
```
**Perché:** campo obbligatorio per la validazione Pydantic di GraphRAG. La sua assenza causava `ValidationError: Field required` all'avvio dell'auto-tuning.

### Completion model — aggiunto `call_args` (identico a `settings.yaml`)
```yaml
call_args:
  extra_headers:
    User-Agent: python-httpx/0.27.0
```

### Embedding model — aggiunto `call_args` (identico a `settings.yaml`)
```yaml
call_args:
  extra_headers:
    User-Agent: python-httpx/0.27.0
  encoding_format: "float"
```

### Vector store — dimensione vettore corretta
```yaml
vector_size: 2560   # era 1536
```

---

## `docker-compose.yml` *(nuovo file)*

Creato per avviare/fermare Neo4j con `docker compose up/down`, replicando il `docker run` documentato nel README.

```yaml
services:
  neo4j:
    image: neo4j:latest
    container_name: graphrag-neo4j
    ports:
      - "7475:7474"
      - "7688:7687"
    environment:
      NEO4J_AUTH: neo4j/graphrag123
    restart: unless-stopped
```

Connessione: `bolt://localhost:7688`, credenziali `neo4j / graphrag123`.

---

## `frontend/app.py`

### `/api/status` — aggiunto `log_offset`
La risposta ora include `log_offset` (indice del primo elemento nella finestra restituita) oltre alle ultime 100 righe di log. Prima il client perdeva il sincronismo non appena il log superava 100 righe (la lunghezza dell'array rimaneva fissa a 100).

### `DELETE /api/runs` *(nuovo endpoint)*
Cancella tutti i run dal database SQLite, rimuove le relative cartelle di output e resetta lo stato in-memory della pipeline.

### `POST /api/reset-pipeline` *(nuovo endpoint)*
Resetta lo stato in-memory della pipeline (utile quando un run rimane bloccato in `running`) e marca come `error` i run `running`/`pending` orfani nel DB.

---

## `frontend/templates/index.html`

### Pulsanti sidebar — ⚡ Reset e 🗑 Clear All
Aggiunti nella header della sidebar accanto al pulsante di refresh esistente. Chiamano rispettivamente `POST /api/reset-pipeline` e `DELETE /api/runs`.

### Pulsante di cancellazione run — visibile su tutti gli stati
Prima il pulsante 🗑 compariva solo sui run in stato `done`. Ora è sempre visibile, permettendo di cancellare anche run bloccati in `running` o `pending`.

### Sincronizzazione log — uso di `log_offset`
Il client ora calcola `totalLen = log_offset + data.log.length` per tracciare la posizione reale nel log completo, evitando il congelamento dell'output dopo 100 righe. Lo scroll al fondo avviene dentro `requestAnimationFrame` per garantire che il DOM sia già aggiornato.

---

## `frontend/static/css/style.css`

### Stile `.topbar-btn.danger`
```css
.topbar-btn.danger { background: #c0392b; color: #fff; border-color: transparent; }
.topbar-btn.danger:hover { background: #e74c3c; }
```
Usato dal pulsante "🗑 Clear All" per distinguerlo visivamente dalle azioni non distruttive.
