# Windows Docker Deployment

## Supported local context

The documented development root is:

```powershell
C:\Docker-Projects\Freight-Calc-Nuevo
```

Requirements:

- Docker Desktop for Windows;
- Linux containers;
- WSL2 backend recommended;
- project `.env` created from `.env.example`;
- the complete repository, including the Django Dockerfile and operational sample-data paths.

## Start

```powershell
cd C:\Docker-Projects\Freight-Calc-Nuevo
Copy-Item .env.example .env -ErrorAction Stop
docker compose up -d --build
docker compose ps
```

Open:

```text
http://localhost:8000/
http://localhost:8000/admin/
```

## Initial setup

```powershell
docker compose exec web python manage.py migrate
docker compose exec web python manage.py setup_access_roles
docker compose exec web python manage.py check
```

Import the STH workbook only from the full project path:

```powershell
docker compose exec web python manage.py import_sth_excel /app/sample_data/V2026.R2_Unlocked_STH_Freight_Calculator.xlsx --client STH --replace
```

## Review-package limitation

The `Create_Files_review_0728.0824.zip` package is a review snapshot, not a guaranteed deployment package. It includes the workbook under `reference_files/`, while the operational commands expect `/app/sample_data/`. The extracted package also does not include `docker/django/Dockerfile` or populated baseline directories.

Therefore:

- use the ZIP for code/documentation review;
- use the complete project at `C:\Docker-Projects\Freight-Calc-Nuevo` for builds and test execution;
- do not infer that Docker is broken solely because the review ZIP omits runtime files.

## Safe diagnostics

```powershell
docker compose ps
docker compose exec web python manage.py check
docker compose exec web python manage.py showmigrations
```

Do not use `docker compose down -v` as an initial repair command because it deletes the PostgreSQL volume.
