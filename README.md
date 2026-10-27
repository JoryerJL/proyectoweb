# Canaco - Blog de noticias

[![CI/CD](https://github.com/JoryerJL/proyectoweb/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/JoryerJL/proyectoweb/actions/workflows/ci-cd.yml)

Blog de noticias de Canaco (Cámara Nacional de Comercio) construido con Django y PostgreSQL. Los lectores consultan noticias, filtran por categoría y comentan; el equipo editorial publica y modera desde un panel con roles. Proyecto del curso "Laboratorio de Desarrollo Web Django".

## Inicio rápido (local)

Requisitos: [uv](https://docs.astral.sh/uv/), Docker y Python 3.14 (uv lo instala por ti).

```bash
docker compose up -d db            # PostgreSQL de desarrollo en localhost:5435
uv sync                            # instala dependencias desde uv.lock
uv run python manage.py migrate
uv run python manage.py seed_news  # opcional: noticias y categorías de ejemplo
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Abre <http://127.0.0.1:8000/>. En desarrollo no necesitas variables de entorno: los valores por defecto de `canaco/settings.py` apuntan a la base de datos del `docker-compose.yml`.

## Funcionalidades

- Sitio público: inicio, noticia, categoría, contáctanos, registro e inicio de sesión.
- Noticias con estado borrador/publicado, galería de imágenes, contador de visitas y editor de contenido enriquecido.
- Comentarios con moderación (pendiente, aprobado, bloqueado).
- CRUD de categorías y de usuarios desde el panel.
- Perfil de usuario: edición de datos, foto y cambio de contraseña.
- Roles: Administrador, Editor y Colaborador; el menú y los permisos cambian según el rol.
- Comando `seed_news` idempotente con contenido de demostración.
- Endpoint de salud `/healthz/` (verifica la conexión a la base de datos).

## Stack

| Capa | Tecnología |
|------|------------|
| Backend | Django 6.1, Python 3.14 |
| Base de datos | PostgreSQL 17 (psycopg 3) |
| Servidor de aplicación | gunicorn |
| Proxy y estáticos | nginx |
| Dependencias | uv (`pyproject.toml`, `uv.lock`) |
| Contenedores | Docker, Docker Compose |
| CI/CD | GitHub Actions, GHCR, AWS CDK (Python), despliegue por OIDC + SSM a AWS EC2 |

## Variables de entorno

Todas son opcionales en desarrollo. En producción se definen en `.env` (plantilla en [`deploy/env.example`](deploy/env.example)).

| Variable | Por defecto | Descripción |
|----------|-------------|-------------|
| `DJANGO_SECRET_KEY` | llave insegura de desarrollo | Obligatoria si `DJANGO_DEBUG=false` |
| `DJANGO_DEBUG` | `true` | Debe ser `false` en producción |
| `DJANGO_ALLOWED_HOSTS` | vacío | Hosts permitidos, separados por comas |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | vacío | Orígenes con esquema, separados por comas |
| `DJANGO_USE_PROXY_SSL_HEADER` | `false` | Confía en `X-Forwarded-Proto` del proxy |
| `DJANGO_SECURE_SSL_REDIRECT` | `false` | Redirige HTTP a HTTPS |
| `DJANGO_SESSION_COOKIE_SECURE` / `DJANGO_CSRF_COOKIE_SECURE` | `false` | Cookies solo por HTTPS |
| `DJANGO_SECURE_HSTS_SECONDS` | `0` | Duración de HSTS |
| `DJANGO_STATIC_ROOT` / `DJANGO_MEDIA_ROOT` | `staticfiles/` / `media/` | Rutas de archivos estáticos y subidos |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | `canaco` | Credenciales de PostgreSQL |
| `DB_HOST`, `DB_PORT` | `localhost`, `5435` | Servidor de PostgreSQL |
| `IMAGE`, `IMAGE_TAG` | `ghcr.io/joryerjl/proyectoweb`, `latest` | Imagen que usa `docker-compose.prod.yml` |
| `HTTP_PORT` | `80` | Puerto publicado por nginx |
| `RUN_SEED` | `0` | Con `1`, carga `seed_news` al arrancar el contenedor |

## Pruebas

Con la base de datos de desarrollo encendida (`docker compose up -d db`):

```bash
uv run python manage.py test
```

Django crea y destruye una base `test_canaco` por su cuenta.

## Producción y Docker

Para probar el stack de producción en cualquier máquina con Docker:

```bash
cp deploy/env.example .env     # editar valores
docker compose -f docker-compose.prod.yml up -d --build
```

Levanta PostgreSQL, la aplicación (gunicorn, migraciones y `collectstatic` automáticos) y nginx (HTTP/HTTPS con certificado autofirmado), en un proyecto Compose aislado (`canaco-prod`) que no toca la base de desarrollo.

## Infraestructura en AWS (CDK)

La infraestructura de producción es código en [`infra/`](infra/README.md) (AWS CDK en Python): una EC2 detrás de Cloudflare, sin SSH (acceso y despliegue por SSM), con etiquetado FinOps, presupuesto mensual y respaldos diarios.

```bash
cd infra && uv sync
cdk deploy -c budgetEmail=tu@correo.com
```

Guía completa (Cloudflare, GitHub, costos, respaldos, rollback): [`docs/despliegue-ec2.md`](docs/despliegue-ec2.md).

## CI/CD

El flujo [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml) ejecuta:

1. **test**: `check`, `makemigrations --check` y pruebas contra PostgreSQL 17 (push y pull request).
2. **build**: construye la imagen; en `master` la publica en `ghcr.io/joryerjl/proyectoweb` (`latest` y SHA corto).
3. **infra**: pruebas de la infraestructura (`pytest`) y `cdk synth`.
4. **deploy**: solo en `master`; asume un rol de AWS por OIDC (sin llaves guardadas), ejecuta el despliegue en la EC2 con SSM y verifica `/healthz/`.

La única configuración requerida en GitHub es la variable `AWS_DEPLOY_ROLE_ARN` del entorno `production` (ver la guía).

## Estructura del proyecto

```
.
├── canaco/                  # Proyecto Django (settings, urls, wsgi)
│   └── env.py               # Lectura de variables de entorno y validación
├── home/                    # Aplicación principal
│   ├── models.py            # Categoría, Publicación, Comentario, Perfil, Archivo
│   ├── views.py, urls.py    # Sitio público, panel y /healthz/
│   ├── roles.py             # Roles y permisos
│   ├── management/commands/ # seed_news
│   └── templates/           # Plantillas de la aplicación
├── static/                  # CSS, JS, fuentes e imágenes
├── media/                   # Archivos subidos (no se versionan)
├── deploy/                  # entrypoint.sh, nginx (HTTPS) y plantilla de .env
├── infra/                   # AWS CDK (Python): VPC, EC2, IAM, presupuesto, respaldos
├── docs/                    # Guías (Docker/Postgres, despliegue en EC2)
├── Dockerfile
├── docker-compose.yml       # PostgreSQL para desarrollo local
├── docker-compose.prod.yml  # Stack de producción
└── .github/workflows/       # CI/CD
```

Las guías del curso están en `docs/`. Para más contexto del producto, consulta [`PRODUCT.md`](PRODUCT.md).
