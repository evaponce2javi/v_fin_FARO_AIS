# Faro AIS — Monitoreo Continuo

## Arquitectura y documentación de archivos

Evolución del Faro AIS original: de un análisis por lotes sobre tres ventanas
históricas fijas, a un sistema de **monitoreo continuo ("casi en tiempo real")**
que consulta Global Fishing Watch automáticamente, procesa lo nuevo y mantiene
el dashboard siempre al día.

---

## Nota de honestidad técnica (leer primero)

"Tiempo real" literal no existe con estas fuentes, y no es culpa del código:

- El radar **Sentinel-1** revisita la zona cada **6 a 12 días**.
- Los **gap events** de GFW se publican con latencia de **días a semanas**.

Lo que este sistema entrega es lo máximo que la física de los datos permite:
**revisar automáticamente a intervalos regulares y alertar apenas GFW publique
algo nuevo**, sin intervención manual y sin re-procesar lo ya visto. El
dashboard muestra siempre un banner de "última actualización" para que la
latencia de la fuente nunca se confunda con una falla del sistema.

---

## Diagrama de flujo

```
            ┌────────────────────────────────────────────────┐
            │  monitor.py  (scheduler — corre siempre)       │
            │  cada N horas (default: 6)                     │
            └──────┬─────────────────────────────────────────┘
                   ▼
   descarga_incremental.py ──> riesgo.py ──> motor.py ──> bitacora.db
   (solo la ventana nueva)     (puntaje       (INSERT OR              
                                0-100 +        IGNORE:                
                                razones)       idempotente)           
                                                    │
                                                    ▼
                                        api.py (FastAPI, :8000)
                                                    │
                                                    ▼
                                        dashboard.html (auto-refresh)
```

---

## Qué hace cada archivo

### `config.py`
Configuración única y centralizada del sistema. Contiene: el polígono GeoJSON
de la Región de Valparaíso (el mismo rectángulo del proyecto original), el
**intervalo de consulta** (`INTERVALO_HORAS = 6`, ajustable), el **tamaño de la
ventana móvil** que se pide a GFW en cada ciclo (`DIAS_VENTANA = 14`, para
cubrir con holgura la revisita de Sentinel-1), las rutas de salida, los puertos
de referencia y la línea de las 5 millas. El token **nunca vive aquí**: se lee
de la variable de entorno `GFW_TOKEN` en tiempo de ejecución. Cambiar el
comportamiento del sistema = editar solo este archivo.

### `descarga_incremental.py`
Reemplazo del `fase1_descarga.py` original. La diferencia clave: en lugar de
tres ventanas históricas fijas, calcula en cada ejecución una **ventana móvil**
(hoy menos `DIAS_VENTANA` → hoy) y descarga detecciones SAR + gap events solo
para ese rango. Mantiene un archivo de estado (`estado_descarga.json`) con la
marca de tiempo de la última consulta exitosa, de modo que si un ciclo falla
(sin red, API caída, pipeline SAR de GFW en mantención — como pasó con julio
2026), el siguiente ciclo recupera el rango pendiente sin dejar huecos. Los CSV
descargados se guardan con sufijo de fecha (`sar_2026-08-09.csv`) y nunca se
sobreescriben: son la evidencia cruda.

### `riesgo.py`
El clasificador explicable del proyecto original (`fase3_riesgo.py`), sin
cambios de lógica — misma suma de señales (+30 sin AIS, +25 ZEE interior, +15
lejos de puerto, +15 persistencia, +10 grupo), mismos niveles
(BAJO/VERIFICAR/MEDIO/ALTO), mismas señales dormidas (`length_m`,
`fishing_score`) y misma disciplina de no acusar a los oscuros costeros. Lo
único que cambia: recibe la ruta del CSV como parámetro en vez de iterar
ventanas fijas, para que el scheduler lo invoque sobre cada descarga nueva.
**Se conserva idéntico a propósito**: el puntaje ya validado con los datos de
octubre 2025 es el activo del proyecto; el monitoreo continuo no debe tocarlo.

### `motor.py`
La bitácora trazable del original (`fase4_motor.py`), con la misma tabla
SQLite, los mismos ID estables por hash SHA-1 y el mismo `INSERT OR IGNORE`.
Esa idempotencia, que en el original era una buena práctica, aquí se vuelve
**la pieza estructural del diseño**: como cada ciclo pide una ventana móvil que
se solapa con la anterior, la mayoría de las detecciones de cada ciclo ya
existen en la base — y el hash garantiza que solo lo genuinamente nuevo se
inserta. El monitoreo continuo funciona *porque* la bitácora era idempotente.
Añade una columna `ciclo_ingreso` (timestamp del ciclo que insertó cada fila)
para poder responder "¿qué llegó nuevo hoy?".

### `monitor.py` ★ (el archivo nuevo de verdad)
El corazón del cambio batch → continuo. Un scheduler en Python puro (bucle con
`time.sleep`, sin dependencias extra) que cada `INTERVALO_HORAS`:

1. Llama a `descarga_incremental.py` (ventana móvil).
2. Pasa lo descargado por `riesgo.py`.
3. Ingresa el resultado a la bitácora vía `motor.py`.
4. Compara el conteo de incursiones antes/después: si hay **nuevas de nivel
   ALTO**, las escribe en `novedades.json` (lo que el dashboard destaca como
   "alertas nuevas desde tu última visita").
5. Registra el ciclo en `monitor.log` (hora, filas nuevas, errores) y
   actualiza `estado_monitor.json` con la marca de "última actualización" que
   consume el banner del dashboard.

Manejo de errores deliberadamente conservador: un ciclo que falla se anota y
se reintenta al ciclo siguiente; el monitor **nunca se cae** por un error de
red o de la API. Se ejecuta con `python monitor.py` y queda corriendo; con
`python monitor.py --una-vez` corre un solo ciclo (útil para probar).

### `api.py`
La API FastAPI del original (`fase4_api.py`) con sus cinco endpoints intactos
(`/resumen`, `/alertas`, `/bitacora`, `/incursion/{id}`, POST de estado) más
dos nuevos:

- **`GET /estado_monitor`** — devuelve la marca de última actualización, el
  próximo ciclo programado y el resultado del último ciclo (éxito/error). Es
  lo que alimenta el banner de frescura del dashboard.
- **`GET /novedades`** — las incursiones ingresadas en el último ciclo,
  para que el panel pueda destacar "lo nuevo" sin que el usuario compare
  listas a mano.

### `dashboard.html`
El panel del original con tres cambios:

1. **Banner de frescura** permanente en la cabecera: "Última actualización:
   [fecha/hora] · próxima consulta: [hora]" (consume `/estado_monitor`). Si el
   último ciclo falló, el banner lo dice en ámbar — la latencia visible, nunca
   escondida.
2. **Auto-refresh**: el panel re-consulta la API cada 5 minutos (configurable
   en una constante al inicio del archivo), sin recargar la página.
3. **Sección "Novedades"**: las alertas ALTO nuevas del último ciclo,
   destacadas arriba de la lista general.

Todo lo demás — mapa Leaflet con la línea de 5 millas, colores por nivel,
detalle con razones, botones de estado del fiscalizador, exportación CSV — se
conserva igual.

### `datos/` (carpeta)
CSV crudos con sufijo de fecha (evidencia, nunca se borran), `bitacora.db`,
`estado_descarga.json`, `estado_monitor.json`, `novedades.json` y
`monitor.log`. Incluye los CSV históricos del proyecto original como respaldo:
si no hay token o no hay red, el sistema completo corre en "modo demo" sobre
esos datos — el mismo principio de respaldo honesto del paquete original.

### `LEEME.md`
Instrucciones de puesta en marcha: instalar dependencias
(`gfw-api-python-client pandas fastapi uvicorn`), exportar `GFW_TOKEN` como
variable de entorno (con el recordatorio explícito de **nunca pegar el token
en código, chats ni repositorios**), y el orden de arranque: `python
monitor.py` en una terminal, `python api.py` en otra, y abrir
`dashboard.html`. Incluye la nota de honestidad para el pitch, heredada del
original: las observaciones son reales; el puntaje y la bitácora son la capa
de interpretación propia. Decir siempre "detecciones sin AIS", nunca "barcos
ilegales".

---

## Decisiones de diseño (y por qué)

| Decisión | Razón |
|---|---|
| Intervalo default de 6 h | Sentinel-1 revisita cada 6–12 días: consultar más seguido no produce datos nuevos, solo gasta cuota de API. 6 h asegura captar cada publicación de GFW con horas de retraso, no días. |
| Ventana móvil de 14 días con solape | GFW publica con retraso variable; una ventana amplia + bitácora idempotente garantiza que nada se pierde y nada se duplica. |
| Scheduler en Python puro (sin cron, sin Celery) | Coherente con la filosofía del original (SQLite en vez de Postgres): la herramienta más simple que resuelve el problema. Migrar a cron/systemd después es trivial. |
| Riesgo y motor sin cambios de lógica | El clasificador validado con octubre 2025 es el activo del proyecto. El monitoreo continuo lo envuelve, no lo reescribe. |
| Banner de frescura obligatorio | La latencia de la fuente es la limitación central del sistema; mostrarla siempre es lo que separa un sistema honesto de una demo que aparenta. |
| Modo demo sin token | El sistema debe poder demostrarse completo (jurado, pitch) sin depender de red ni credenciales. |

---

## Alcance declarado

Este sistema es **monitoreo continuo con la latencia de sus fuentes** (horas a
días), no vigilancia al minuto. Para un jurado técnico esa precisión de
vocabulario es una fortaleza, no una debilidad: demuestra que el equipo
entiende la física de sus datos.
