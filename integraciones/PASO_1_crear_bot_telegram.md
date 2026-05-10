# 🤖 PASO 1 — Crear tu bot de Telegram (3 minutos)

## 1. Abrir BotFather

1. Abre **Telegram** (celular o escritorio).
2. Arriba en la lupa, busca: `@BotFather`
3. Selecciona el oficial: tiene check azul ✓ y dice **BotFather**.

## 2. Crear el bot

Escríbele estos comandos uno por uno:

```
/newbot
```

→ Te pide un **nombre** (el que aparece en el chat):
```
Organizador Diego
```

→ Te pide un **username** (terminado en `bot`, único en Telegram):
```
diego_organizador_bot
```
> Si está tomado, prueba otra cosa: `diegof_org_bot`, `dfo_organizador_bot`...

## 3. Guardar el TOKEN

BotFather te responde con algo así:

```
Done! Congratulations on your new bot.
...
Use this token to access the HTTP API:
123456789:AAFooBarBazQuxQuux-AbcDefGhiJklMno
```

**👉 COPIA ESE TOKEN.** Lo vas a usar en n8n.

> ⚠️ NO lo compartas. Quien lo tenga puede controlar tu bot.

## 4. Obtener TU chat_id

1. Busca tu nuevo bot en Telegram (pega su username arriba en la lupa).
2. Abre el chat con él y dale **START** o escríbele `hola`.
3. En tu **navegador**, abre esta URL (reemplaza `TU_TOKEN`):

```
https://api.telegram.org/botTU_TOKEN/getUpdates
```

Ejemplo real:
```
https://api.telegram.org/bot123456789:AAFooBar.../getUpdates
```

4. Verás algo como:

```json
{
  "ok": true,
  "result": [{
    "message": {
      "chat": {
        "id": 987654321,         ← ESTE es tu chat_id
        "first_name": "Diego",
        "type": "private"
      },
      "text": "hola"
    }
  }]
}
```

**👉 COPIA EL NÚMERO `id`**. Ese es tu chat_id.

## 5. (Opcional) Mejorar el bot

Vuelve a `@BotFather` y ejecuta:

```
/setdescription
```
→ Selecciona tu bot → escribe:
```
Tu organizador personal. Comandos: /plan /tarea /habito /cumpli /menu
```

```
/setcommands
```
→ Selecciona tu bot → pega esto:
```
plan - ☀️ Ver mi plan de hoy
tarea - 📌 Agregar una tarea nueva
habito - 🎯 Marcar un hábito cumplido
cumpli - ✅ Marcar tarea cumplida
empresa - 🏢 Gestionar empresas/proyectos
menu - 📋 Menú principal con botones
```

Ahora al escribir `/` en el chat verás autocompletado de tus comandos.

---

## ✅ Checklist antes del PASO 2

- [ ] Tengo el TOKEN del bot (lo guardo en seguro)
- [ ] Tengo mi chat_id (número)
- [ ] Le envié "hola" al bot y respondió (aunque sea con silencio)
- [ ] (Opcional) configuré comandos con autocompletado

**Cuando tengas estos 2 datos (TOKEN + chat_id) pégamelos en el chat o ponlos en `datos/config.json` y seguimos con el PASO 2: importar los workflows en n8n.**
