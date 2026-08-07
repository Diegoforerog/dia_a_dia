# 📅 Día a día PRO — Planificador maestro

> Centro de mando de la vida de la pareja (Diego + Esposa): proyectos, calendarios,
> hábitos y comidas, con avisos al celular de cada uno.
> Inspirado en el modelo SCRUM de **Clazz**, pero personal y para dos personas.

**Última actualización:** 2026-08-07

---

## 0. Decisiones tomadas (con Diego)

| Tema | Decisión |
|------|----------|
| Proyectos | SCRUM: **Épicas → Historias de usuario → Subtareas**, con **canvas Kanban** (arrastrar). Como Clazz pero personal. |
| Personas | 2 personas (Diego + Esposa). **Sin roles/permisos pesados.** Cada historia/tarea tiene un **responsable**. |
| Plan del día | **Unificado**: junta reuniones + tarjetas del tablero + hábitos + comida del día. |
| Notificaciones | **Ambos**: Web Push (PWA, como La Peurcatón) **+** Telegram, **por persona**. |
| Calendarios | Cada calendario tiene un **dueño** (persona). Los avisos de ese calendario llegan **solo a esa persona**. |
| Hábitos | **Mixto**: unos personales (por persona, con su racha) y otros de pareja (cuentan para ambos). |
| Comidas | En conjunto. **Recetas + menú semanal + despensa (inventario) + lista de mercado automática + IA que sugiere según gustos.** Gustos se capturan dentro de la app. |
| Acceso | **Selector simple** "soy Diego / soy Esposa" (sin contraseña; el celular recuerda). |
| Stack | Se mantiene **Flask + HTML/JS sin build**. Se agrega **PWA** (manifest + service worker). Almacén **JSON + Postgres** (patrón `cargar`/`guardar` actual). Deploy Easypanel/Docker. |

---

## 1. Visión (mapa)

```
DÍA A DÍA PRO  (pareja: Diego + Esposa)
│
├─ 👤 PERSONAS        selector "soy X"; contexto de persona en toda la app
│
├─ 📁 PROYECTOS       Cliente → Proyecto → Épica → Historia → Subtareas
│                     🟦 Canvas Kanban: Backlog · Planeado · En progreso · QA · Bloqueado · Hecho
│                     responsable por tarjeta · filtro por persona/épica
│
├─ 📅 CALENDARIOS     cada calendario pertenece a una persona (dueño)
│                     → recordatorios de eventos solo a esa persona
│
├─ 🎯 HÁBITOS         mixto: personales (racha por persona) + de pareja
│
├─ 🍽️ COMIDAS         recetas · menú semanal · despensa · lista de mercado · IA sugiere
│
├─ 🔔 AVISOS          Web Push (PWA) + Telegram, enrutados por persona
│
└─ 🗓️ PLAN DEL DÍA    reuniones + tarjetas + hábitos + comida → resumen matutino por persona (IA)
```

---

## 2. Modelo de datos (nuevas y modificadas)

Todo se guarda con el patrón actual `cargar("X.json")` / `guardar("X.json", data)` →
respaldo JSON + tabla Postgres (esquema `organizador`).

### 2.1 Personas (nuevo)
```
personas: { id, nombre, color, activo,
            telegram_chat_id?,           # para avisos Telegram
            push_subscriptions: [ ... ]  # suscripciones Web Push (1 por dispositivo)
          }
```

### 2.2 Proyectos SCRUM (nuevo/extiende)
```
proyectos   : { id, cliente_id, nombre, estado, prioridad, deadline, descripcion }   # ya existe
epicas      : { id, proyecto_id, titulo, descripcion, prioridad, estado(OPEN/IN_PROGRESS/DONE), orden }
historias   : { id, proyecto_id, epica_id?, titulo, descripcion,
                responsable_id,                    # persona
                prioridad(baja/media/alta/critica),
                estado(backlog/planeado/en_progreso/qa/bloqueado/hecho),
                etiquetas[], estimacion_horas?, puntos?,
                fecha_objetivo?, motivo_bloqueo?, criterios[ {texto, hecho} ],
                orden, creada, completada_en }
subtareas   : { id, historia_id, titulo, hecho, responsable_id?, orden }
```
> Migración: las 3 `actividades` actuales y los 3 `proyectos` se convierten en historias
> dentro de sus proyectos, estado `backlog`, sin perder nada.

### 2.3 Calendarios (extiende)
```
calendarios: { ..., persona_id }   # + dueño de la persona que recibe los avisos
```

### 2.4 Hábitos (extiende)
```
habitos: { ..., alcance("personal"|"pareja"), persona_id? }   # personal → tiene dueño; pareja → ambos
# racha por persona: los de pareja cuentan cuando cualquiera lo cumple
```

### 2.5 Comidas + despensa (nuevo)
```
recetas       : { id, nombre, tipo(desayuno/almuerzo/cena/snack), gustos[](tags),
                  ingredientes: [ {item, cantidad, unidad} ], pasos, favorita }
menu_semanal  : { semana(YYYY-Www), dias: { lunes:{desayuno:receta_id, almuerzo:.., cena:..}, ... } }
despensa      : { item, unidad, estado("hay"|"poco"|"agotado"), cantidad? }
lista_mercado : { generada_at, items: [ {item, cantidad, unidad, origen("menu"|"despensa"|"manual"), comprado} ] }
gustos        : { no_come[], le_gusta[], restricciones[], preferencias_texto }   # para la IA
```
**Lista de mercado automática** = (ingredientes del menú de la semana)
− (lo que hay en despensa) + (items marcados `poco`/`agotado`).

**IA sugiere menú** = según `gustos` + lo que hay en `despensa` (evita repetir, aprovecha lo que hay).

### 2.6 Notificaciones (nuevo)
```
push_subscriptions: por persona (VAPID web-push).
enrutador de avisos: (evento, persona) → enviar a sus canales (Web Push + Telegram).
```

---

## 3. Canvas (tablero Kanban)

- Una columna por estado: **Backlog · Planeado · En progreso · QA · Bloqueado · Hecho**.
- Tarjeta = historia (título, responsable con color, prioridad, etiquetas, fecha, avisos de vencido).
- **Arrastrar y soltar** entre columnas (HTML5 nativo, sin librerías de build).
- Filtros: por proyecto, por responsable ("lo mío / lo de ella / todo"), por épica.
- Clic en tarjeta → panel de detalle (subtareas, criterios de aceptación, bloqueo, notas).

---

## 4. Plan del día unificado

```
PLAN DE HOY (por persona)  =  📅 Reuniones de SUS calendarios
                            +  ✅ Historias/subtareas con fecha=hoy o "En progreso" y responsable = esa persona
                            +  🎯 Hábitos del día (personales de esa persona + de pareja)
                            +  🍽️ Comida del día (del menú)
```
La IA de la mañana arma el plan y lo manda al celular de cada uno (Web Push + Telegram).

---

## 5. Roadmap por fases (cada fase es entregable y probable)

| Fase | Nombre | Qué incluye | Resultado visible |
|------|--------|-------------|-------------------|
| **0** | Cimientos pareja | Personas + selector "soy X" + contexto de persona en toda la app + **PWA instalable** | Instalan la web en el celular y eligen quién son |
| **1** | Proyectos SCRUM + Canvas | Épicas/Historias/Subtareas + tablero Kanban + panel de historia + **migración** de datos actuales | Ven y mueven tarjetas; sus proyectos actuales ya están dentro |
| **2** | Calendarios + Avisos | Dueño por calendario + **Web Push (VAPID)** + Telegram por persona + enrutador; recordatorios de eventos por persona | A cada uno le llegan SUS avisos al celular |
| **3** | Hábitos mixtos | Alcance personal/pareja + racha por persona + filtro | Cada uno lleva sus hábitos; los de pareja cuentan para ambos |
| **4** | Comidas + Despensa | Recetas + menú semanal + **despensa** + **lista de mercado automática** + IA sugiere + aviso del día | Planean la semana; la lista de compras se arma sola |
| **5** | Plan del día unificado | Junta todo + resumen matutino por persona (IA) | Cada mañana, el plan completo de cada uno al celular |

**Regla de seguridad:** todo se guarda también en JSON como respaldo (como ya funciona hoy),
así ningún cambio pone en riesgo los datos.

---

## 6. Pendientes / a decidir sobre la marcha

- Capturar gustos: pantalla de preferencias dentro de la app (Fase 4).
- ¿Menú semanal empieza lunes o domingo? (default: lunes).
- ¿La despensa se llena manual al inicio o se va poblando con lo que compran? (default: se va poblando).
- Claves VAPID y `chat_id` de cada persona → configurables desde Admin.
