# Development Guide

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- Docker + Docker Compose
- PostgreSQL 15 (or use Docker)
- LM Studio (for local LLM)

### Setup

```bash
# 1. Clone the repository
git clone https://github.com/kitapoe-ops/openclaw-sandbox-rpg.git
cd openclaw-sandbox-rpg

# 2. Copy environment variables
cp .env.example .env
# Edit .env with your API keys

# 3. Start services with Docker
docker-compose up -d

# 4. Install backend dependencies
cd backend
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# 5. Install frontend dependencies
cd ../frontend
npm install
```

### Running Locally

```bash
# Terminal 1: Backend
cd backend
uvicorn main:app --reload --port 8000

# Terminal 2: Frontend
cd frontend
npm run dev

# Terminal 3: LM Studio (for local LLM)
# Open LM Studio app, load Qwen2.5-14B, enable API server on port 1234
```

### Access Points

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/ws/game/{character_id}

## Project Structure

```
.
├── backend/              # FastAPI backend
│   ├── api/             # REST endpoints
│   ├── ws/              # WebSocket handlers
│   ├── models/          # Database models
│   ├── tests/           # Unit + integration tests
│   ├── semantic_gradient.py
│   ├── state_machine.py
│   ├── physics_lock.py
│   ├── choice_validator.py
│   ├── world_lore_db.py
│   ├── llm_client.py
│   ├── config.py
│   └── main.py
│
├── frontend/            # Vue 3 frontend
│   ├── src/
│   │   ├── components/  # Vue components
│   │   ├── views/       # Page views
│   │   ├── router/
│   │   ├── stores/      # Pinia stores
│   │   ├── App.vue
│   │   └── main.ts
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   └── tsconfig.json
│
├── docs/                # Documentation
│   ├── SCHEMAS/        # JSON/YAML schemas
│   ├── PROMPTS/        # LLM prompt templates
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEVELOPMENT.md
│   └── CHANGELOG.md
│
├── worlds/              # World content packages
│   ├── dnd_5e_forgotten_realms.yaml
│   └── ...
│
├── deploy/              # Deployment configs
│   ├── docker/
│   └── scripts/
│
├── .github/
│   └── workflows/       # CI/CD
│
└── docker-compose.yml
```

## Development Workflow

### Adding a New Endpoint

1. Add route in `backend/api/<resource>.py`
2. Add validation against schema in `docs/SCHEMAS/`
3. Add tests in `backend/tests/`
4. Update `docs/API.md`

### Adding a New Schema

1. Create JSON schema in `docs/SCHEMAS/`
2. Reference in backend code
3. Add validation tests
4. Update `docs/ARCHITECTURE.md` if needed

### Adding a New LLM Prompt

1. Create prompt template in `docs/PROMPTS/`
2. Add few-shot examples in `docs/PROMPTS/few_shots/`
3. Test with actual LLM
4. Document in `docs/ARCHITECTURE.md`

### Adding a New World Parameter

1. Edit world YAML in `worlds/<world>.yaml`
2. Add semantic gradient (5 levels)
3. Add prompt descriptions for LLM
4. Add trigger conditions

### Adding a New NPC

1. Add to world YAML `npcs:` section
2. Set type (narrative/functional)
3. Add stats, dialogue hooks, relationships
4. Test in game

## Testing

### Backend Tests

```bash
cd backend
pytest tests/ -v
pytest tests/ --cov=. --cov-report=html
```

### Frontend Tests

```bash
cd frontend
npm run test
npm run type-check
```

### Integration Test

```bash
# Start all services
docker-compose up -d

# Run integration test
cd backend
pytest tests/integration/ -v
```

## Code Style

### Python

- Format: Black (line length 100)
- Lint: Ruff
- Type hints: Required for all functions
- Docstrings: Google style

```python
def example_function(param1: str, param2: int) -> bool:
    """
    Brief description.

    Args:
        param1: Description
        param2: Description

    Returns:
        Description
    """
    return True
```

### TypeScript / Vue

- Format: Prettier
- Lint: ESLint
- Components: Vue 3 Composition API with `<script setup>`
- TypeScript: Strict mode

```vue
<script setup lang="ts">
import { ref } from 'vue'

interface Props {
  title: string
}

const props = defineProps<Props>()
</script>
```

## Database Migrations

> TODO: Set up Alembic

```bash
# Create migration
alembic revision --autogenerate -m "Add characters table"

# Apply migration
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Debugging

### Backend

```bash
# Enable debug mode
export DEBUG=true
uvicorn main:app --reload --log-level debug
```

### Frontend

Vue DevTools browser extension.

### LLM Calls

Set `LOG_LEVEL=DEBUG` to see all LLM request/response in logs.

## Common Tasks

### Reset Database

```bash
docker-compose down -v
docker-compose up -d
```

### Update Dependencies

```bash
# Backend
cd backend
pip install --upgrade -r requirements.txt

# Frontend
cd frontend
npm update
```

### Run Linter

```bash
# Backend
cd backend
ruff check .
black --check .

# Frontend
cd frontend
npm run lint
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Add character creation endpoint
fix: Resolve physics lock edge case
docs: Update API reference
test: Add physics lock unit tests
refactor: Simplify state machine
chore: Update dependencies
```

## License

MIT — see [LICENSE](../LICENSE)

---

## Wave 1 Quickstart (current delivery)

### 1. Install backend deps

`ash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
`

### 2. Run tests

`ash
.\.venv\Scripts\python.exe -m pytest backend/tests/ -v
`

Expected: **133 passed, 1 skipped, 0 failed** (1 skip is the cloud API key test, which is skipped if no API key is set).

### 3. Seed demo data

`ash
.\.venv\Scripts\python.exe backend/seed_demo.py
`

Loads worlds/dnd_5e_forgotten_realms.yaml (1,025 lines, 10 NPCs, 21 items, 5 locations, 3 quests, 3 starter characters) into the in-memory store and creates char_starter_aria (half-elf ranger 雅莉亞・月羽).

The script prints CHARACTER_ID=... and WORLD_ID=... on success.

### 4. Run the HTTP server

`ash
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765
`

### 5. Smoke-test the API

`ash
# Health
curl http://127.0.0.1:8765/health

# Get the demo character
curl http://127.0.0.1:8765/api/character/char_starter_aria

# Get the world state
curl http://127.0.0.1:8765/api/world/dnd_5e_forgotten_realms/state
`

### 6. Full HTTP smoke test (6 steps)

`powershell
.\scripts\smoke_test.ps1
`

Verifies: health → character load → world state → action submit (400 expected) → scene seed → action submit (200 with scene).

### Persistence modes

Default persistence_mode is memory (in-process InMemoryStore; data lost on restart).

Switch to SQLAlchemy-backed persistence:

`powershell
="database"
="postgresql+asyncpg://user:pass@localhost:5432/sandbox_rpg"
# or for SQLite (dev):
="sqlite+aiosqlite:///./sandbox_rpg.db"

.\.venv\Scripts\python.exe -m alembic upgrade head
`

## Wave 1 Audit History

R1-14B audit completed. All 4 issues resolved:

1. **db.py::init_db race condition** — fixed with syncio.Lock + idempotency flag (ackend/db.py)
2. **Persistence not integrated** — all 4 API endpoints now use persistence.get_store() dispatcher
3. **Schema field mismatch** — state_change unified to {old, new, reason} format
4. **YAML enum violations** — steady→calm, high→elated

Branch: local-wave1-stub (pushed to remote as snapshot of Wave 1 delivery; main is v3.7 production).
