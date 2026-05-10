# 📅 Conectar tus calendarios de Gmail

> 🎯 **Para qué:** leer tus eventos de Gmail para que el planificador IA los respete como bloques fijos.

## Paso a paso (10 minutos, una sola vez)

### 1. Crear proyecto en Google Cloud
1. Entra a https://console.cloud.google.com/
2. Arriba a la izquierda → **Nuevo proyecto** → nombre: `Organizador Diego` → Crear.
3. Selecciona el proyecto recién creado.

### 2. Activar la API de Calendario
1. Buscador arriba: escribe **Google Calendar API**.
2. Click en el resultado → **Habilitar**.

### 3. Crear credenciales OAuth
1. Menú izquierdo → **APIs y servicios** → **Credenciales**.
2. **+ Crear credenciales** → **ID de cliente de OAuth**.
3. Si te pide configurar pantalla de consentimiento:
   - Tipo: **Externo**
   - Nombre app: `Organizador Diego`
   - Email de soporte: tu correo
   - Guarda y continúa hasta el final.
   - En **Usuarios de prueba**: agrega TU correo de Gmail.
4. Vuelve a **Credenciales** → **+ Crear credenciales** → **ID de cliente de OAuth**:
   - Tipo de aplicación: **Aplicación de escritorio**
   - Nombre: `Organizador local`
   - Crear.
5. Click en **Descargar JSON**.

### 4. Guardar el archivo aquí
Mueve el archivo descargado a:

```
Organizador_Calendarios/integraciones/credentials.json
```

### 5. Marcar tus calendarios en `datos/calendarios.json`
Edita el archivo y pon TUS correos reales, con `"activo": true`:

```json
{
  "calendarios_gmail": [
    {
      "id": "personal",
      "email": "tu_correo@gmail.com",
      "nombre_para_mostrar": "Personal",
      "empresa_asociada": "personal",
      "color": "#4ECDC4",
      "activo": true
    },
    {
      "id": "dropi",
      "email": "tu_correo_negocio@gmail.com",
      "nombre_para_mostrar": "Dropi",
      "empresa_asociada": "dropi",
      "color": "#FF6B35",
      "activo": true
    }
  ]
}
```

### 6. Instalar librerías
```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

### 7. Primera ejecución
```bash
cd "Personal/Organizador_Calendarios"
python scripts/leer_google_calendar.py
```

Se abrirá el navegador, das permiso, y se guarda `token.json` automáticamente.
A partir de aquí ya no te pedirá login.

---

## ¿Qué hace exactamente?
✅ Lee eventos del DÍA de TODOS tus calendarios marcados activos
✅ Los guarda en `datos/registros/YYYY-MM-DD.json` como `eventos_gmail`
✅ El planificador IA los respeta como bloques fijos al armar el plan

## ¿Y si quiero que también CREE eventos en Gmail?
Cambia el SCOPE en `scripts/leer_google_calendar.py` de `calendar.readonly` a `calendar` y agrégame esa función. Por ahora va solo lectura (más seguro).

## Seguridad
- `credentials.json` y `token.json` son SOLO TUYOS, no los compartas.
- Están en `integraciones/` que NO debe subirse a ningún Git público.
