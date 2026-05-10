# 🚀 Orden recomendado para conectar TODO

Sigue este orden, cada paso toma pocos minutos.

```
PASO 0 ── Instalar dependencias Mac           (3 min)
   │
   ▼
PASO 1 ── Crear bot Telegram                  (3 min)
   │      ↳ Obtienes: TOKEN, chat_id
   ▼
PASO A ── Levantar API local                  (1 min)
   │      ↳ python scripts/api.py
   ▼
PASO 3 ── Cloudflare Tunnel                   (5 min)
   │      ↳ Obtienes: URL pública
   ▼
PASO 2 ── Importar workflows en n8n           (10 min)
   │      ↳ Conectas TODO
   ▼
🎉 LISTO — Probar /menu en Telegram
```

---

## PASO 0 — Instalar lo necesario en tu Mac

```bash
cd "Personal/Organizador_Calendarios"

# Librerías Python
pip install flask flask-cors openai

# (Opcional, para conectar Google Calendar después)
pip install google-auth google-auth-oauthlib google-api-python-client

# Túnel
brew install cloudflared
```

## PASO A — Levantar la API y la web admin

```bash
# Variables de entorno
export OPENAI_API_KEY="sk-..."
export ORGANIZADOR_TOKEN="un-token-secreto-largo-y-aleatorio"

# Correr la API
python scripts/api.py
```

Verás:
```
🚀 API local en http://localhost:5050
   Token de seguridad: un-token-secreto-largo-y-aleatorio
   Tablero: http://localhost:5050/
```

Abre en navegador:
- **Tablero del día:** http://localhost:5050/
- **Admin (configurar empresas, proyectos, hábitos):** http://localhost:5050/tablero/admin.html

> 💡 La primera vez que entres al admin, pega tu token en la pestaña **🔧 Config**.

---

## Continúa con los pasos en este orden

1. **[PASO 1: Crear bot Telegram](PASO_1_crear_bot_telegram.md)**
2. **[PASO 3: Cloudflare Tunnel](PASO_3_cloudflare_tunnel.md)**
3. **[PASO 2: Importar workflows n8n](PASO_2_importar_n8n.md)**

---

## 🧪 Verificación final

Al terminar, en Telegram escríbele al bot:

```
/menu
```

Si recibes la lista de comandos = TODO funciona ✅

Prueba estos:
```
/plan                                          ← ver plan del día
/tarea dropi | Revisar campaña de ads          ← agregar tarea
/menu                                          ← ver opciones
```

---

## 🆘 Problemas comunes

| Problema | Solución |
|---|---|
| `/menu` no responde | n8n no encuentra credenciales Telegram, revisa PASO 2 |
| n8n da error 401 al llamar API | Token mismatched, revisa `ORGANIZADOR_API_TOKEN` |
| n8n da error de conexión | URL del túnel mal o Mac apagada |
| Plan genera vacío | Falta `OPENAI_API_KEY` en la Mac donde corre la API |
| `pip install flask` falla | Usa `pip3` o `python3 -m pip install flask` |
