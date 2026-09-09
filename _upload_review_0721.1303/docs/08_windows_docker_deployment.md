# Windows Docker Deployment

Requirements:

- Docker Desktop for Windows
- WSL2 backend recommended

Steps:

```bash
copy .env.example .env
docker compose up --build
```

Open:

- `http://localhost:8000/`
- `http://localhost:8000/admin/`
