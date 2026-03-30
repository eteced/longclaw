# LongClaw - Multi-Agent Task Server

A multi-agent task management system inspired by OpenClaw, focused on task-driven multi-agent collaboration.

## Architecture

```
Channel (QQ/Telegram/Web/API)
    │
    ▼
┌─────────────┐
│ Resident    │  ← Persistent agent with personality, handles chat + task dispatch
│ Agent       │
└──────┬──────┘
       │ Task created
       ▼
┌─────────────┐
│ Task Owner  │  ← Task manager, decomposes/plans/tracks
│ Agent       │
└──────┬──────┘
       │ Decomposed to subtasks
       ▼
┌─────────────┐
│ Worker      │  ← Executes specific tasks, destroyed after completion
│ Agent(s)    │
└─────────────┘
```

## Tech Stack

- **Backend**: Python (FastAPI) - async-friendly, great AI ecosystem
- **Database**: MariaDB - persistent storage
- **Message Queue**: Redis - lightweight, for task dispatch and state sync
- **LLM**: OpenAI-compatible API (supports multiple providers)

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)

### Using Docker Compose (Recommended)

1. Clone the repository:

```bash
git clone <repository-url>
cd longclaw
```

2. Create environment file:

```bash
cp backend/.env.example backend/.env
```

3. Edit `backend/.env` and configure your LLM API keys:

```bash
LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=your_api_key_here
```

4. Start the services:

```bash
docker-compose up -d
```

5. Check the API:

```bash
curl http://localhost:8001/health
```

### Local Development

1. Create a virtual environment:

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Set up environment variables:

```bash
cp .env.example .env
# Edit .env with your configuration
```

4. Start MariaDB and Redis (using Docker):

```bash
docker run -d --name longclaw-db \
  -e MYSQL_ROOT_PASSWORD=root \
  -e MYSQL_DATABASE=longclaw \
  -e MYSQL_USER=longclaw \
  -e MYSQL_PASSWORD=longclaw \
  -p 3306:3306 \
  mariadb:11

docker run -d --name longclaw-redis \
  -p 6379:6379 \
  redis:7-alpine
```

5. Run the server:

```bash
python -m backend.main
```

Or using uvicorn directly:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8001
```

## API Documentation

Once the server is running, access the interactive API documentation at:

- Swagger UI: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

### Main Endpoints

#### Tasks

- `GET /api/tasks` - List tasks
- `GET /api/tasks/{id}` - Get task details
- `POST /api/tasks` - Create a task
- `PATCH /api/tasks/{id}` - Update a task
- `POST /api/tasks/{id}/terminate` - Terminate a task
- `GET /api/tasks/{id}/subtasks` - List subtasks

#### Agents

- `GET /api/agents` - List agents
- `GET /api/agents/{id}` - Get agent details
- `GET /api/agents/{id}/messages` - Get agent messages
- `GET /api/agents/{id}/summary` - Get agent summary

#### Messages

- `GET /api/messages/task/{task_id}` - Get task messages
- `GET /api/messages/conversation/{conversation_id}` - Get conversation messages
- `POST /api/messages` - Create a message

#### Channels

- `GET /api/channels` - List channels
- `GET /api/channels/{id}` - Get channel details
- `POST /api/channels` - Create a channel
- `PUT /api/channels/{id}` - Update a channel
- `DELETE /api/channels/{id}` - Delete a channel

## Project Structure

```
longclaw/
├── backend/
│   ├── main.py                  # FastAPI entry point
│   ├── config.py                # Configuration management
│   ├── database.py              # MariaDB connection
│   ├── models/                  # SQLAlchemy models
│   │   ├── agent.py             # Agent model
│   │   ├── task.py              # Task model
│   │   ├── subtask.py           # Subtask model
│   │   ├── message.py           # Message model
│   │   ├── conversation.py      # Conversation model
│   │   └── channel.py           # Channel model
│   ├── services/
│   │   ├── agent_service.py     # Agent lifecycle management
│   │   ├── task_service.py      # Task CRUD
│   │   ├── llm_service.py       # LLM API wrapper
│   │   ├── message_service.py   # Message storage + Redis pub/sub
│   │   ├── channel_service.py   # Channel management
│   │   └── scheduler_service.py # Background tasks
│   ├── agents/
│   │   ├── base_agent.py        # Agent base class
│   │   ├── resident_agent.py    # Resident agent (Phase 2)
│   │   ├── owner_agent.py       # Task owner agent (Phase 2)
│   │   └── worker_agent.py      # Worker agent (Phase 2)
│   ├── channels/
│   │   ├── base_channel.py      # Channel base class
│   │   ├── qqbot_channel.py     # QQ channel (Phase 4)
│   │   └── web_channel.py       # Web channel (Phase 4)
│   └── api/                     # REST API endpoints
│       ├── agents.py
│       ├── tasks.py
│       ├── messages.py
│       └── channels.py
├── docker-compose.yml
└── README.md
```

## Configuration

Configuration is done through environment variables. See `.env.example` for all available options.

### LLM Providers

The system supports multiple LLM providers through OpenAI-compatible APIs:

```bash
# OpenAI
LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

# DeepSeek
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

## Development Phases

### Phase 1: Core Framework (Current)
- [x] Project initialization
- [x] Database models
- [x] Agent base class
- [x] LLM service
- [x] Message system
- [x] Basic REST API
- [x] Docker Compose

### Phase 2: Agent Implementation
- [ ] Resident Agent
- [ ] Task Owner Agent
- [ ] Worker Agent
- [ ] Agent communication

### Phase 3: Dashboard
- [ ] React frontend
- [ ] Task management UI
- [ ] WebSocket real-time updates

### Phase 4: Channel Integration
- [ ] QQBot channel
- [ ] Telegram channel
- [ ] API channel

### Phase 5: Advanced Features
- [ ] Disconnection recovery
- [ ] Task pause/resume
- [ ] Agent personality UI
- [ ] Task templates

## License

Modified MIT
