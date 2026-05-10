# 💬 Recibir el plan por Telegram

> 🎯 **Para qué:** notificación instantánea en tu celular. Más rápido que Gmail.

## Paso a paso (3 minutos)

### 1. Crear un bot en Telegram
1. Abre Telegram y busca: `@BotFather`
2. Mándale: `/newbot`
3. Te pedirá un nombre (ej: `Organizador Diego Bot`)
4. Te pedirá un username terminado en `bot` (ej: `diego_organizador_bot`)
5. Te dará un **TOKEN** tipo: `123456789:ABCDEFghijklmnop...`
6. Copia ese token.

### 2. Obtener tu chat_id
1. Busca tu nuevo bot y mándale cualquier mensaje (ej: "hola").
2. En el navegador abre:
   ```
   https://api.telegram.org/bot[TU_TOKEN]/getUpdates
   ```
   (reemplaza `[TU_TOKEN]` por el token de arriba)
3. Busca en la respuesta `"chat":{"id": NUMERO`. Ese número es tu chat_id.

### 3. Configurar en `datos/config.json`
```json
"telegram": {
  "bot_token": "123456789:ABCDEFghijklmnop...",
  "chat_id": "123456789"
}
```

Y activa avisos:
```json
"avisos": { ..., "telegram": true, ... }
```

### 4. Probar
```bash
python scripts/enviar_telegram.py
```

Deberías recibir el plan formateado en tu Telegram al instante.

---

## ¿Y WhatsApp?
WhatsApp es más complicado: requiere WhatsApp Business API o servicios pagos (Twilio, etc).
**Recomendación:** usa Telegram. Es gratis, instantáneo, sin trabas.

Si insistes en WhatsApp, opciones:
- **Twilio WhatsApp API** (~$5/mes)
- **Servicios como CallMeBot** (gratis pero limitado)
- Avísame cuál y lo agregamos.
