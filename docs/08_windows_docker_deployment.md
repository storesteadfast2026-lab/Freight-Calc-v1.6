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

## Repository versus review packages

The package `Create_Files_review_0818.1318.zip` is a source/evidence review
snapshot, not a deployment package. It places the controlled workbook under
`reference_files/` and omits the Django Dockerfile, the populated operational
`sample_data/` tree and the paired validation baselines. Those omissions do not
prove that the full repository lacks the files.

Therefore:

- use a review ZIP only for the evidence it actually contains;
- use the complete project at `C:\Docker-Projects\Freight-Calc-Nuevo` for builds and test execution;
- confirm the current repository contains `docker/django/Dockerfile`,
  `sample_data/`, fixtures, baselines and reports before running commands;
- do not infer that Docker is broken solely because an old review ZIP omitted
  runtime files.

## Safe diagnostics

```powershell
docker compose ps
docker compose exec web python manage.py check
docker compose exec web python manage.py showmigrations
```

Do not use `docker compose down -v` as an initial repair command because it deletes the PostgreSQL volume.
