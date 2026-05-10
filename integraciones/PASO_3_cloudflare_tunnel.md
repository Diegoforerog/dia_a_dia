# 🔌 PASO 3 — Conectar tu n8n VPS con tu Mac (Cloudflare Tunnel)

## ¿Por qué?

```
   🌍 INTERNET
       │
       ▼
   🌐 n8n en tu VPS
       │
       │ Necesita llegar a TU MAC
       │ (donde están los archivos JSON)
       ▼
   🖥️  TU MAC
       │
       └─ API local en http://localhost:5050
          (NO está expuesta a internet)
```

**Solución:** Cloudflare Tunnel crea una URL pública (ej: `https://organizador.tu-dominio.com`) que apunta a tu `localhost:5050` de forma segura y **gratis**.

> ⚠️ Necesitas que tu Mac esté encendida y la API corriendo cuando n8n quiera consultar.

---

## Opción A — Cloudflare Tunnel (recomendada, gratis, sin dominio)

### 1. Instalar `cloudflared` en tu Mac
```bash
brew install cloudflared
```

### 2. Túnel rápido (sin cuenta, URL temporal)
```bash
cloudflared tunnel --url http://localhost:5050
```

Verás algo así:
```
https://abc-xyz-123.trycloudflare.com
```

**Esa es tu URL pública.** Cópiala y úsala en `ORGANIZADOR_API_URL` de n8n.

> ⚠️ Esta URL cambia cada vez que reinicias el túnel. Para algo permanente, sigue la opción B.

### 3. Túnel permanente (con cuenta Cloudflare gratis)

#### A. Crear cuenta y autenticar
```bash
cloudflared tunnel login
```
Se abre el navegador, eliges (o creas) una cuenta Cloudflare.

#### B. Crear el túnel
```bash
cloudflared tunnel create organizador
```
Esto crea un ID único.

#### C. Configurar dominio
Si tienes un dominio en Cloudflare:
```bash
cloudflared tunnel route dns organizador organizador.tu-dominio.com
```

Si NO tienes dominio: usa un `*.trycloudflare.com` random (paso 2).

#### D. Crear archivo de configuración
Edita `~/.cloudflared/config.yml`:
```yaml
tunnel: organizador
credentials-file: /Users/diegoforero/.cloudflared/<TU_ID>.json

ingress:
  - hostname: organizador.tu-dominio.com
    service: http://localhost:5050
  - service: http_status:404
```

#### E. Correr el túnel
```bash
cloudflared tunnel run organizador
```

#### F. Para que arranque solo al prender Mac
```bash
sudo cloudflared service install
```

---

## Opción B — ngrok (alternativa, plan gratis con limitaciones)

```bash
brew install ngrok
ngrok config add-authtoken TU_TOKEN_DE_NGROK
ngrok http 5050
```

Te da una URL tipo `https://abc123.ngrok-free.app`. Plan gratis se limita a sesiones cortas.

---

## Opción C — Tailscale (si quieres extra seguridad)

Si solo TU n8n del VPS necesita acceder, instala Tailscale tanto en VPS como en Mac. La Mac queda accesible por IP privada Tailscale (`100.x.x.x`).

```bash
# En Mac
brew install --cask tailscale
# En VPS
curl -fsSL https://tailscale.com/install.sh | sh
```

Luego en n8n usas `http://100.x.x.x:5050` como `ORGANIZADOR_API_URL`.

---

## ✅ Cómo verificar que funciona

Una vez tengas la URL pública:

```bash
curl https://organizador.tu-dominio.com/api/health
```

Debería responder:
```json
{"ok": true, "fecha": "2026-05-10"}
```

Y con autenticación:
```bash
curl -H "X-API-Token: tu-token" https://organizador.tu-dominio.com/api/empresas
```

---

## 🔄 Flujo completo cuando todo está conectado

```
   🕖 7:00 AM Lunes
        │
        ▼
   n8n VPS dispara el cron
        │
        ▼ POST https://organizador.tu-dominio.com/api/plan/generar
        │
   🔌 Cloudflare Tunnel
        │
        ▼
   🖥️  Tu Mac (API Flask)
        │
        ▼ Lee JSONs + llama OpenAI gpt-4o-mini
        │
        ▼ Guarda plan en datos/registros/2026-05-12.json
        │
        ▼ Devuelve plan a n8n
        │
   n8n formatea como markdown
        │
        ▼
   💬 Llega a tu Telegram
        │
        ▼
   ☕ Tomas café leyendo el plan
```

---

## 💡 Recomendación

Para empezar: **Opción A — túnel rápido**. En 30 segundos lo tienes funcionando.
Cuando ya funcione y lo quieras dejar permanente: **túnel permanente con dominio**.
