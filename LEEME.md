# Faro AIS — Monitoreo Continuo

Evolución del Faro AIS original: de análisis por lotes a **monitoreo
continuo** que consulta Global Fishing Watch cada 6 horas, procesa lo
nuevo y mantiene el dashboard siempre al día, con la latencia de sus
fuentes visible en un banner permanente.

La arquitectura completa y el porqué de cada decisión están en
`ARQUITECTURA.md`.

---

## Instalación (una sola vez)

```
python -m pip install gfw-api-python-client pandas fastapi uvicorn
```

## El token (⚠️ leer)

El sistema lee el token de GFW desde la **variable de entorno**
`GFW_TOKEN`. **Nunca** lo pegues en el código, en chats, capturas ni
repositorios — es una credencial: quien la tenga puede usar tu cuota y
tu identidad ante GFW. Si alguna vez quedó expuesta, revócala y genera
una nueva (gratis) en globalfishingwatch.org/our-apis/tokens.

```
Linux/Mac:            export GFW_TOKEN="tu_token"
Windows PowerShell:   $env:GFW_TOKEN="tu_token"
Windows cmd:          set GFW_TOKEN=tu_token
```

**Sin token, el sistema igual funciona completo en modo demo** sobre los
CSV históricos incluidos en `datos/` (octubre 2024, octubre 2025 y los
apagados de julio 2026). Ideal para pitch sin depender de red.

## Puesta en marcha

Terminal 1 — el monitor (queda corriendo, un ciclo cada 6 h):
```
python monitor.py
```
Para probar un solo ciclo: `python monitor.py --una-vez`

Terminal 2 — la API:
```
python api.py
```

Luego abrir `dashboard.html` con doble click. El panel se auto-refresca
cada 5 minutos y muestra en el banner la última actualización y la
próxima consulta programada.

## Archivos

| Archivo | Qué hace |
|---|---|
| `config.py` | Toda la configuración: intervalo (6 h), ventana móvil (14 días), zona, puertos, rutas. |
| `descarga_incremental.py` | Descarga la ventana móvil desde GFW; recupera huecos si un ciclo falló. |
| `riesgo.py` | Clasificador explicable 0–100 con razones en texto (idéntico al original). |
| `motor.py` | Bitácora SQLite idempotente + columna `ciclo_ingreso` ("¿qué llegó nuevo?"). |
| `monitor.py` | El scheduler: descarga → clasifica → ingresa → publica novedades → registra. |
| `api.py` | 7 endpoints: los 5 originales + `/estado_monitor` y `/novedades`. |
| `dashboard.html` | Panel con banner de frescura, novedades destacadas, mapa, bitácora y export CSV. |
| `datos/` | CSV crudos (evidencia, nunca se borran), `bitacora.db`, estados y log del monitor. |

## Nota de honestidad para el pitch

Las observaciones son reales (Global Fishing Watch / Sentinel-1 / AIS);
el puntaje, los niveles y la bitácora son la capa de interpretación
propia del proyecto. Este sistema es **monitoreo continuo con la
latencia de sus fuentes** (Sentinel-1 revisita cada 6–12 días; los gap
events se publican con días de retraso) — no vigilancia al minuto, y el
banner lo dice siempre. Decir "detecciones sin AIS" o "barcos oscuros",
nunca "barcos ilegales".

---

## Alcance y límites declarados (leer antes de presentar)

Faro AIS mide **ocultamiento**, no nacionalidad ni ilegalidad. Tres límites que
conviene declarar antes de que los pregunte un jurado:

1. **No atribuye bandera.** Un barco sin AIS no declara nacionalidad: por
   construcción, el sistema no puede afirmar de qué país es una detección
   oscura. En los datos de octubre 2025, las 64 detecciones oscuras no tienen
   bandera, y entre las 75 que sí transmiten no aparece ninguna china. El
   sistema respalda la existencia de embarcaciones que se ocultan, no la
   nacionalidad que los pescadores denuncian.
2. **No acusa a los costeros.** Un oscuro dentro de las 5 millas puede ser un
   artesanal legítimo sin AIS. Sin dato de eslora no hay forma de distinguirlo,
   así que su puntaje tiene un tope en VERIFICAR (44). Queda registrado para
   revisión humana; el sistema nunca lo eleva a alerta.
3. **No es tiempo real ni intercepción.** Sentinel-1 revisita cada 6-12 días.
   El valor está en la evidencia y el patrón, no en la inmediatez.
