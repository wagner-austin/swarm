# AI Task Execution System

A distributed, AI-powered task execution platform capable of decomposing complex requests into subtasks and orchestrating specialized workers to complete them.

## 🎯 What This Is

An intelligent task assistant that can handle high-level requests like:
- "Research upcoming environmental bills and prepare talking points"
- "Analyze and improve the logging system in my codebase"
- "Do my latest homework assignment"
- "Monitor this website daily and summarize changes"

The system breaks down these complex tasks into subtasks, routes them to appropriate workers (web browsers, code analyzers, LLMs), and coordinates execution across a distributed infrastructure.

## 🚀 Key Features

- **Task Decomposition**: Automatically breaks complex tasks into manageable subtasks
- **Distributed Workers**: Scale from 1 to 1000+ specialized workers
- **Multiple Frontends**: Discord, Telegram, Web API, CLI (Discord is just ONE interface)
- **Capability-Based Routing**: Workers advertise skills, tasks route to best match
- **Local LLM Support**: Run private AI models on your GPU for sensitive tasks
- **Platform Agnostic**: Deploy on local machines, Docker, Kubernetes, or cloud

## 📋 Quick Start

### Prerequisites
- Python 3.11+
- Poetry
- Docker (optional, for containerized deployment)
- NVIDIA GPU with 24GB+ VRAM (optional, for local LLMs)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd swarm

# Install dependencies
poetry install --with dev

# Install browser automation tools
poetry run playwright install chromium

# Copy environment template
cp .env.example .env
```

### Configuration

Edit `.env` with your settings:

```ini
# Redis for task queue (required)
REDIS_URL=redis://localhost:6379/0

# Frontend configurations (use any or all)
DISCORD_TOKEN=your-token-here      # For Discord frontend
TELEGRAM_TOKEN=your-token-here     # For Telegram frontend
API_KEY=your-api-key               # For REST API

# Worker configuration
BROWSER_HEADLESS=true              # Run browsers in background
WORKER_CONCURRENCY=5               # Tasks per worker

# Optional: AI Models
OPENAI_API_KEY=your-key           # For GPT-4 tasks
LOCAL_MODEL_PATH=/models/llama-2-70b.gguf  # For private LLM
```

### Running the System

**Development (single machine):**
```bash
# Start all services (Redis, Flower, autoscaler, and swarm)
docker-compose up -d

# Or run components separately
make run            # Start main swarm service
make celery-worker  # Start a Celery worker
make flower         # Start Flower monitoring UI

# View logs
docker-compose logs -f swarm
docker-compose logs -f autoscaler
```

**Production (Kubernetes):**
```bash
# Deploy to Kubernetes cluster
kubectl apply -f k8s/

# Scale workers
kubectl scale deployment/worker --replicas=50
```

## 🏗️ Architecture

```
User Request → Frontend (Discord/Telegram/API)
                ↓
           Swarm Core → Celery Task Queue (Redis)
                ↓
         [Browser Tasks]
         /      |       \
   [Navigate] [Click] [Extract]
      ↓         ↓         ↓
   Celery    Celery    Celery
   Worker1   Worker2   Worker3
      ↓         ↓         ↓
         Result Backend
                ↓
         Response to User

Monitoring: Flower UI (port 5555)
Autoscaling: Celery Autoscaler
```

### Port Configuration

- **9200**: Swarm metrics (Discord frontend)
- **5555**: Flower (Celery monitoring UI)
- **9090**: Prometheus
- **3000**: Grafana
- **3100**: Loki
- **6379**: Redis

## 🔧 Development

### Running Tests
```bash
make test      # Run all tests
make lint      # Lint and format code
make check     # Type checking with mypy
```

### Project Structure
```
project/
├── swarm/                  # Core system
│   ├── distributed/       # Task queue and worker management
│   ├── browser/          # Browser automation workers
│   ├── plugins/          # Frontend adapters
│   └── tasks/            # Task decomposition logic
├── frontends/            # Multi-platform interfaces
├── workers/              # Specialized worker types
└── k8s/                  # Kubernetes manifests
```

## 📚 Documentation

- [PLAN.md](PLAN.md) - Detailed implementation roadmap
- [CLAUDE.md](CLAUDE.md) - AI collaboration guidelines and architecture notes
- [docs/SCALING_ARCHITECTURE.md](docs/SCALING_ARCHITECTURE.md) - Distributed system design

## 🎯 Current Status & Roadmap

**Phase 1 (Current)**: Fixing critical issues
- Job acknowledgment bugs
- Queue metrics integration
- Removing Discord-centric assumptions

**Phase 2**: Migrate to Celery
- Replace custom job queue
- Add task persistence
- Implement retry logic

**Phase 3**: Local LLM Integration
- Add GPU-accelerated workers
- Private model support
- Capability-based routing

**Phase 4**: Multi-Frontend Support
- Abstract interface layer
- Telegram frontend
- REST API
- Web UI

## 🤝 Contributing

This project uses production-grade standards:
- All code must have type annotations
- Integration tests over mocks
- Clear documentation for decisions
- Consider existing tools before building custom solutions

See [CLAUDE.md](CLAUDE.md) for detailed collaboration guidelines.

## 📜 License

[Your license here]

---

**Note**: This project is under active development. The vision is to create an AI-powered workforce that can tackle complex real-world problems at scale.