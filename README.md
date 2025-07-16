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
cd DiscordBot  # TODO: Rename to TaskForce

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
# Start all services
docker-compose up -d

# Or run components separately
make run            # Start main service
make worker         # Start a worker
make autoscaler     # Start autoscaler
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
         Task Decomposer
                ↓
        [Task: Research bills]
         /      |       \
   [Browse]  [Analyze]  [Summarize]
      ↓         ↓           ↓
   Worker1   Worker2    Worker3 (LLM)
      ↓         ↓           ↓
         Result Aggregator
                ↓
         Response to User
```

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
├── bot/                    # Core system (TODO: rename to 'core')
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
- Telegram bot
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