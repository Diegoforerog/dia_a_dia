# 📅 Día a día — Organizador

Sistema personal para organizar clientes, proyectos, tareas, hábitos y calendarios.
Tablero web + bot de Telegram + IA para armar tu plan diario.

## Stack

- **Backend**: Flask + Gunicorn (Python 3.12)
- **DB**: PostgreSQL 17 (esquema `organizador`)
- **Frontend**: HTML/JS + FullCalendar.js (sin build step)
- **IA**: OpenAI gpt-4o-mini para generar resúmenes y planes
- **Calendarios**: iCal URLs (read-only, sin OAuth)
- **Bot**: Telegram + n8n workflows

## Desarrollo local

```bash
pip3 install -r requirements.txt
cp .env.example .env  # rellenar con tus valores
python3 scripts/api.py
```

Tablero: <http://localhost:5050>
Admin:   <http://localhost:5050/tablero/admin.html>

## Producción (Easypanel / Docker)

```bash
docker build -t dia-a-dia .
docker run -p 5050:5050 --env-file .env dia-a-dia
```

Healthcheck: `GET /api/health` devuelve `{"ok": true, "fecha": "YYYY-MM-DD"}`.

## Variables de entorno

Ver [`.env.example`](.env.example). Todas obligatorias salvo `GOOGLE_REDIRECT_URI`
(solo si usas OAuth de Google Calendar — el flujo iCal no lo necesita).

## Estructura

```
scripts/      → API Flask + scripts CLI
tablero/      → UI estática (admin, agenda, tablero del día)
datos/        → JSON locales como espejo de la DB (legacy/backup)
db/           → schema.sql + migraciones + script de carga inicial
integraciones/ → Documentación paso-a-paso de Telegram, Google, n8n
```

## Endpoints clave

| Método | Ruta | Para |
|---|---|---|
| GET | `/api/health` | Healthcheck |
| GET/POST/PUT/DELETE | `/api/clientes` | CRUD de clientes |
| GET/POST/PUT/DELETE | `/api/proyectos` | CRUD de proyectos |
| GET/POST/PUT/DELETE | `/api/tareas` | CRUD de tareas |
| GET/POST/PUT/DELETE | `/api/habitos` | CRUD de hábitos |
| GET/POST/DELETE | `/api/calendarios` | CRUD de calendarios |
| GET | `/api/calendarios/eventos_rango?desde=&hasta=` | Eventos del calendario |
| GET | `/api/metricas/habitos` | Métricas: heatmap, rachas, logros |
| GET | `/api/metricas/proyectos` | Métricas: progreso, tareas/día |
| POST | `/api/plan/generar` | IA arma plan del día |

Todos requieren header `X-API-Token: <ORGANIZADOR_TOKEN>` salvo `/health` y `/local-token`.
