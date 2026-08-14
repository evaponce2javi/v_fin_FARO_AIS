"""
FARO AIS CONTINUO — API para el dashboard
==========================================
Los cinco endpoints del original intactos (/resumen, /alertas, /bitacora,
/incursion/{id}, POST de estado) más dos nuevos:

  GET /estado_monitor  -> última actualización, próximo ciclo, resultado
                          del último ciclo (alimenta el banner de frescura)
  GET /novedades       -> incursiones ALTO ingresadas en el último ciclo
                          (lo que el panel destaca como "nuevo")

Ejecutar:   python api.py
Probar:     http://127.0.0.1:8000/resumen
Docs:       http://127.0.0.1:8000/docs
"""
import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import config

config.entrar_a_datos()

app = FastAPI(
    title="Faro AIS API — Monitoreo Continuo", version="1.0",
    description="Alertas y bitácora de barcos oscuros — Región de Valparaíso")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])


def consultar(sql, argumentos=()):
    conexion = sqlite3.connect(config.BASE_DE_DATOS)
    conexion.row_factory = sqlite3.Row
    filas = [dict(fila) for fila in conexion.execute(sql, argumentos).fetchall()]
    conexion.close()
    return filas


def _leer_json(ruta, si_no_existe):
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as archivo:
            return json.load(archivo)
    return si_no_existe


@app.get("/resumen")
def resumen():
    """KPIs del panel principal."""
    total = consultar("SELECT COUNT(*) n FROM incursiones")[0]["n"]
    alto = consultar("SELECT COUNT(*) n FROM incursiones WHERE nivel='ALTO'")[0]["n"]
    niveles = {fila["nivel"]: fila["n"] for fila in consultar(
        "SELECT nivel, COUNT(*) n FROM incursiones GROUP BY nivel")}
    pico = consultar("SELECT fecha, COUNT(*) n FROM incursiones WHERE fuente='SAR' "
                     "GROUP BY fecha ORDER BY n DESC LIMIT 1")
    por_dia = consultar("SELECT fecha, COUNT(*) n FROM incursiones WHERE fuente='SAR' "
                        "GROUP BY fecha ORDER BY fecha")
    return {"total_incursiones": total, "alertas_activas": alto,
            "por_nivel": niveles, "dia_pico": pico[0] if pico else None,
            "incursiones_por_dia": por_dia}


@app.get("/alertas")
def alertas():
    """Alertas activas (nivel ALTO), ordenadas por gravedad."""
    return consultar("SELECT * FROM incursiones WHERE nivel='ALTO' "
                     "ORDER BY puntaje DESC, fecha DESC")


@app.get("/bitacora")
def bitacora(nivel: str | None = None, fuente: str | None = None,
             estado: str | None = None):
    """Historial completo con filtros opcionales."""
    sql, argumentos = "SELECT * FROM incursiones WHERE 1=1", []
    for campo, valor in (("nivel", nivel), ("fuente", fuente), ("estado", estado)):
        if valor:
            sql += f" AND {campo}=?"
            argumentos.append(valor)
    return consultar(sql + " ORDER BY fecha DESC", argumentos)


@app.get("/incursion/{iid}")
def incursion(iid: str):
    """Detalle de una incursión con sus razones (la evidencia)."""
    filas = consultar("SELECT * FROM incursiones WHERE id=?", (iid,))
    if not filas:
        raise HTTPException(404, "incursión no encontrada")
    return filas[0]


class CambioEstado(BaseModel):
    estado: str  # Registrada | En revisión | Denunciada


@app.post("/incursion/{iid}/estado")
def cambiar_estado(iid: str, cambio: CambioEstado):
    """Flujo del fiscalizador: Registrada -> En revisión -> Denunciada."""
    if cambio.estado not in ("Registrada", "En revisión", "Denunciada"):
        raise HTTPException(400, "estado inválido")
    conexion = sqlite3.connect(config.BASE_DE_DATOS)
    cursor = conexion.execute("UPDATE incursiones SET estado=? WHERE id=?",
                              (cambio.estado, iid))
    conexion.commit()
    conexion.close()
    if cursor.rowcount == 0:
        raise HTTPException(404, "incursión no encontrada")
    return {"id": iid, "estado": cambio.estado}


@app.get("/estado_monitor")
def estado_monitor():
    """Frescura del sistema: alimenta el banner del dashboard."""
    return _leer_json(config.ESTADO_MONITOR, {
        "ultima_actualizacion": None, "proximo_ciclo": None,
        "modo": "sin_iniciar", "error": "el monitor aún no ha corrido ningún ciclo",
    })


@app.get("/novedades")
def novedades():
    """Incursiones ALTO ingresadas en el último ciclo del monitor."""
    return _leer_json(config.ARCHIVO_NOVEDADES, [])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
