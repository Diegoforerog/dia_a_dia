# 📧 Recibir el plan por correo cada mañana

> 🎯 **Para qué:** que cada mañana llegue tu plan del día a tu Gmail.

## Paso a paso (5 minutos)

### 1. Crear contraseña de aplicación en Gmail
> Esto es porque Gmail ya no permite la contraseña normal en apps.

1. Activa la verificación en 2 pasos: https://myaccount.google.com/security
2. Una vez activa, entra a https://myaccount.google.com/apppasswords
3. Crea una contraseña para "Organizador" (Mac).
4. Te dará un código de 16 letras tipo: `abcd efgh ijkl mnop`.
5. Copia esa contraseña.

### 2. Guardar la contraseña como variable de entorno
En tu Terminal:

```bash
export EMAIL_PASSWORD="abcdefghijklmnop"
```

Para que persista, agrégala a `~/.zshrc`:

```bash
echo 'export EMAIL_PASSWORD="abcdefghijklmnop"' >> ~/.zshrc
```

### 3. Configurar remitente/destinatario
Edita `datos/config.json`:

```json
"email": {
  "remitente": "tu_correo@gmail.com",
  "smtp_servidor": "smtp.gmail.com",
  "smtp_puerto": 587,
  "destinatario": "tu_correo@gmail.com"
}
```

### 4. Activar en avisos
En el mismo `config.json`:
```json
"avisos": { ..., "email": true, ... }
```

### 5. Probar
```bash
python scripts/enviar_email.py
```

Deberías recibir el plan del día en tu correo.

## Automatizar todas las mañanas
En Mac, agregar un cron (Terminal):

```bash
crontab -e
```

Agrega esta línea (envío 7:00 am todos los días):

```
0 7 * * * cd "/Users/diegoforero/Documents/_Proyecto Claude/Personal/Organizador_Calendarios" && /usr/bin/python3 scripts/plan_manana.py && /usr/bin/python3 scripts/enviar_email.py
```
