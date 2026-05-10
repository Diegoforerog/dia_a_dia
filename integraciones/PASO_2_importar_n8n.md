# 🤖 PASO 2 — Importar workflows en tu n8n (10 minutos)

## ¿Qué vas a importar?

| Workflow | Qué hace | Trigger |
|---|---|---|
| **01 Router Telegram** | Recibe `/plan`, `/tarea`, `/menu` y responde | Mensajes del bot |
| **02 Plan matutino** | Genera plan IA y lo envía a tu Telegram | Cron 7:00 AM diario |
| **03 Cierre noche** | Resumen del día + saludo de cierre | Cron 9:00 PM diario |

Están en: `integraciones/n8n_workflows/`

---

## 1. Crear las credenciales en n8n

### A) Credencial Telegram
1. En tu n8n: **Credentials** (izquierda) → **+ New**.
2. Busca **Telegram API**.
3. Pega el **TOKEN** del bot (del PASO 1).
4. Guarda. Anota el nombre (ej: `Telegram Organizador`).

### B) Variables de entorno en n8n
En tu VPS, edita el archivo de configuración de n8n (típicamente `~/.n8n/.env` o `docker-compose.yml`) y agrega:

```bash
ORGANIZADOR_API_URL=https://tu-tunnel.tu-dominio.com
ORGANIZADOR_API_TOKEN=tu-token-secreto-largo
TELEGRAM_CHAT_ID=987654321
```

> 🔌 `ORGANIZADOR_API_URL` lo obtienes en el PASO 3 (Cloudflare Tunnel).
> Por ahora pon un placeholder, lo cambiamos después.

Reinicia n8n para que tome las variables:
```bash
docker compose restart n8n     # si usas Docker
# o
pm2 restart n8n                # si usas PM2
```

---

## 2. Importar los 3 workflows

Por cada archivo en `integraciones/n8n_workflows/`:

1. En n8n: **Workflows** → **+ Add workflow** (esquina superior derecha).
2. Click en los **3 puntos ⋮** arriba → **Import from File**.
3. Selecciona el JSON correspondiente.

### Ajustar credencial en cada workflow
Después de importar:
1. Abre el workflow.
2. Cualquier nodo en rojo (suele ser Telegram) → click → en **Credential** elige `Telegram Organizador`.
3. Guarda (Cmd/Ctrl+S).

---

## 3. Probar el router de Telegram

1. Abre el workflow **Organizador - Router Telegram**.
2. Click en **Activo** (toggle arriba a la derecha).
3. En Telegram, escríbele al bot:
   ```
   /menu
   ```
4. Deberías recibir el menú con todos los comandos.

---

## 4. Comandos disponibles

| Comando | Qué hace |
|---|---|
| `/plan` | Te muestra el plan del día actual |
| `/tarea dropi \| Buscar productos nuevos` | Agrega tarea a la empresa Dropi |
| `/tarea personal \| Llamar al médico` | Tarea para área personal |
| `/menu` | Lista todos los comandos |
| `/start` | Bienvenida |

> 💡 Formato `/tarea`: usa `|` para separar empresa del título.

---

## 5. Activar los cron (matutino y nocturno)

1. Abre **Organizador - Plan matutino 7AM** → toggle **Activo**.
2. Abre **Organizador - Cierre 9PM** → toggle **Activo**.

Listo. Cada día a las 7am recibirás tu plan, y a las 9pm el cierre.

---

## ⚠️ Antes de funcionar 100%

Necesitas que tu n8n del VPS pueda llegar a tu API local (Mac).
**Sigue el PASO 3: Cloudflare Tunnel** (5 minutos).
