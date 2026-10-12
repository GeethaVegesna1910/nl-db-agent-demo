# Natural-language database agent

Ask questions about a shop's data in plain English and get back an answer, the
SQL that produced it, a chart and a table. Built on PostgreSQL, Claude, FastAPI
and React.

> "Show revenue by category" → *Furniture is the top category by revenue with
> $184,276.54 (32% of the total).* plus a bar chart, the rows and the SQL.

The agent is **read-only**. It can look at data but never change it, and it can
never read the saved chat history. Three separate layers enforce that: the AI is
told to refuse, a SQL validator rejects anything that isn't a single `SELECT`,
and queries run as a database user that only has `SELECT` on the business tables.

## What's inside (the phases)

| Phase | What was built | Main files |
| --- | --- | --- |
| 1 | Project setup, database tables and sample data | `scripts/init_db.py`, `scripts/seed_data.py` |
| 2 | Safe query layer: validator, read-only executor with a 1,000-row cap and a 30s timeout | `app/security/`, `app/database/` |
| 3 | Chat memory that survives restarts, and the read-only database user | `app/context/conversation_store.py` |
| 4 | AI SQL generator (Claude), with retries and refusals | `app/llm/query_generator.py` |
| 5 | The agent that connects everything, and a terminal chat | `app/agent.py`, `chat.py` |
| 6 | Business definitions, so "revenue" always means the same thing | `metadata/business_semantics.yaml` |
| 7 | Result formatter: summary sentence, chart type, highlights, follow-ups | `app/format/result_formatter.py` |
| 8 | Web API | `app/api/main.py` |
| 9 | Chat website | `frontend/` |
| 10 | Docker, monitoring and a smoke test | `docker-compose.yml`, `scripts/smoke_test.sh` |

## Run it with Docker

You need Docker Desktop and an Anthropic API key.

**1. Create your `.env`** (see the note on secrets below):

```bash
cp .env.example .env
# then open .env and set ANTHROPIC_API_KEY
```

**2. Start everything:**

```bash
docker compose up -d --build
```

**3. First time only: create the tables and load the sample data.** These
scripts run on your machine and talk to the database on port 5433:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
python scripts/init_db.py
python scripts/seed_data.py
```

**4. Open it:**

| What | Address |
| --- | --- |
| Chat website | http://localhost:8080 |
| API (try it in the browser) | http://localhost:8001/docs |
| API health | http://localhost:8001/health |
| API metrics | http://localhost:8001/metrics |
| Prometheus (monitoring) | http://localhost:9091 |
| PostgreSQL | `localhost:5433` |

Stop it with `docker compose down`. The database's data is kept in a Docker
volume, so it is still there next time.

To check the whole stack in one go:

```bash
./scripts/smoke_test.sh
```

It starts the stack, asks one real question, and prints PASS or FAIL for the
API, the metrics, the website and Prometheus.

## Run it without Docker (for development)

Only the database runs in Docker; the API and website run on your machine and
reload when you edit them.

```bash
docker compose up -d postgres

# Terminal 1: the API
source venv/bin/activate
uvicorn app.api.main:app --reload --port 8001

# Terminal 2: the website (http://localhost:5173)
cd frontend
cp .env.example .env      # set VITE_API_URL=http://localhost:8001
npm install
npm run dev
```

The Docker API also uses port 8001, so stop it first (`docker compose stop api`).
There is a terminal chat too: `python chat.py` (`--list`, `--last`,
`--continue <id>`).

## Run the tests

```bash
# Python (needs the database running)
source venv/bin/activate
pytest

# Website
cd frontend
npm test
```

Some Python tests (`test_sql_generator.py`, `test_agent.py`, `test_accuracy.py`)
call the real Claude API, about 20 calls and a few cents per full run. They are
skipped automatically when `ANTHROPIC_API_KEY` is not set. To run only the free
ones:

```bash
pytest tests/test_sql_validator.py tests/test_database.py tests/test_context.py \
       tests/test_formatter.py tests/test_api.py
```

Each test file can also be run on its own for a PASS/FAIL list, for example
`python tests/test_accuracy.py`, which ends with a score such as `10/10`.

## Secrets: `.env` is never committed

- `.env` holds your API key. It is listed in `.gitignore`, so git ignores it,
  and in `.dockerignore`, so it is never copied into a Docker image.
- Docker passes its values to the API container only when the container starts.
- `.env.example` is the template that *is* committed. It contains no real secrets.
- If a key is ever committed by accident, revoke it in the Anthropic Console
  and create a new one. Deleting the file afterwards is not enough.

## Things to know before real use

- **`user_id` is a placeholder.** The API trusts whoever the caller says they
  are. Add real sign-in before real users.
- **The database passwords are demo values** (`postgres`, `agent_readonly`).
  Change them anywhere other than your own machine.
- **`/metrics` is open** on the same port as the API. Restrict it if the API is
  ever exposed to the internet.
