"""
FARO AIS CONTINUO — Bitácora trazable (SQLite)
===============================================
La misma bitácora del fase4_motor.py original: tabla incursiones, ID
estable por hash SHA-1 del contenido, INSERT OR IGNORE. Esa idempotencia
—que en el original era una buena práctica— aquí es LA pieza estructural
del diseño: como cada ciclo pide una ventana móvil que se solapa con la
anterior, la mayoría de las detecciones ya existen en la base, y el hash
garantiza que solo lo genuinamente nuevo se inserta.

Novedad respecto del original: la columna ciclo_ingreso (timestamp del
ciclo que insertó cada fila) permite responder "¿qué llegó nuevo hoy?".

Entrada:  alertas_*.csv (y fase3_alertas_*.csv por compatibilidad)
          eventos_apagado_ais_*.csv
Salida:   bitacora.db, bitacora_export.csv, resumen.json
"""
import ast
import glob
import hashlib
import json
import sqlite3

import pandas as pd

import config


def id_estable(fuente, contenido):
    """ID reproducible por contenido: misma incursión => mismo ID."""
    base = f"{fuente}|{contenido}"
    return "INC-" + hashlib.sha1(base.encode()).hexdigest()[:8].upper()


def crear_tabla(conexion):
    conexion.execute("""CREATE TABLE IF NOT EXISTS incursiones (
        id TEXT PRIMARY KEY,
        fuente TEXT,            -- SAR (radar) o GAP (apagado de AIS)
        fecha TEXT,
        lat REAL, lon REAL,
        zona TEXT,
        puntaje INTEGER,
        nivel TEXT,
        razones TEXT,
        barco TEXT,             -- solo GAP trae identidad
        mmsi TEXT,
        estado TEXT DEFAULT 'Registrada',   -- Registrada -> En revisión -> Denunciada
        registrado_en TEXT DEFAULT (datetime('now')),
        ciclo_ingreso TEXT      -- qué ciclo del monitor insertó esta fila
    )""")


def cargar_alertas_sar(conexion, ciclo):
    """Ingresa las alertas clasificadas. Devuelve los IDs realmente nuevos."""
    nuevos = []
    rutas = sorted(glob.glob("alertas_*.csv") + glob.glob("fase3_alertas_*.csv"))
    for ruta in rutas:
        alertas = pd.read_csv(ruta)
        for _, fila in alertas.iterrows():
            iid = id_estable("SAR", f"{fila.date}|{fila.lat}|{fila.lon}")
            cursor = conexion.execute(
                """INSERT OR IGNORE INTO incursiones
                   (id, fuente, fecha, lat, lon, zona, puntaje, nivel, razones, ciclo_ingreso)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (iid, "SAR", fila.date, fila.lat, fila.lon, fila.zona,
                 int(fila.puntaje), str(fila.nivel), fila.razones, ciclo))
            if cursor.rowcount == 1:   # 1 = insertada de verdad; 0 = ya existía
                nuevos.append(iid)
    return nuevos


def cargar_apagados(conexion, ciclo):
    """Ingresa los gap events (apagados intencionales). Devuelve IDs nuevos."""
    import os
    nuevos = []
    for ruta in sorted(glob.glob("eventos_apagado_ais_*.csv")):
        if os.path.getsize(ruta) < 10:
            continue
        eventos = pd.read_csv(ruta)
        for _, fila in eventos.iterrows():
            barco = (ast.literal_eval(fila["vessel"])
                     if isinstance(fila.get("vessel"), str) else {})
            duracion_h = (pd.to_datetime(fila["end"])
                          - pd.to_datetime(fila["start"])).total_seconds() / 3600
            agravantes = []
            if not barco.get("flag"):
                agravantes.append("sin bandera declarada")
            if str(barco.get("ssvid", "")).startswith("94"):
                agravantes.append("MMSI de rango irregular")
            nivel = "ALTO" if (duracion_h > 24 or agravantes) else "MEDIO"
            razones = (f"apagado intencional de AIS por {duracion_h:.0f} h"
                       + (" | " + " | ".join(agravantes) if agravantes else ""))
            iid = id_estable("GAP", fila["id"])
            cursor = conexion.execute(
                """INSERT OR IGNORE INTO incursiones
                   (id, fuente, fecha, lat, lon, zona, puntaje, nivel, razones,
                    barco, mmsi, ciclo_ingreso)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (iid, "GAP", str(fila["start"])[:10], None, None, "trayecto",
                 90 if nivel == "ALTO" else 60, nivel, razones,
                 barco.get("name"), str(barco.get("ssvid", "")), ciclo))
            if cursor.rowcount == 1:
                nuevos.append(iid)
    return nuevos


def exportar(conexion):
    """Exporta la bitácora completa y el resumen de KPIs."""
    bitacora = pd.read_sql(
        "SELECT * FROM incursiones ORDER BY puntaje DESC, fecha DESC", conexion)
    bitacora.to_csv(config.EXPORT_BITACORA, index=False)

    solo_sar = bitacora[bitacora.fuente == "SAR"]
    resumen = {
        "total_incursiones": int(len(bitacora)),
        "alertas_activas_ALTO": int((bitacora.nivel == "ALTO").sum()),
        "por_nivel": bitacora.nivel.value_counts().to_dict(),
        "por_fuente": bitacora.fuente.value_counts().to_dict(),
        "por_estado": bitacora.estado.value_counts().to_dict(),
        "ultima_fecha_registrada": str(bitacora.fecha.max()),
        "dia_pico": (solo_sar.groupby("fecha").size().idxmax()
                     if not solo_sar.empty else None),
        "detecciones_dia_pico": (int(solo_sar.groupby("fecha").size().max())
                                 if not solo_sar.empty else 0),
    }
    with open("resumen.json", "w", encoding="utf-8") as archivo:
        json.dump(resumen, archivo, ensure_ascii=False, indent=2)
    return resumen


def ingestar(ciclo):
    """Punto de entrada del monitor: carga todo lo disponible en la bitácora.

    Devuelve (ids_nuevos, resumen). Ejecutarlo dos veces con los mismos
    datos no duplica nada: propiedad indispensable en un registro de evidencia.
    """
    conexion = sqlite3.connect(config.BASE_DE_DATOS)
    crear_tabla(conexion)
    nuevos = cargar_alertas_sar(conexion, ciclo) + cargar_apagados(conexion, ciclo)
    conexion.commit()
    resumen = exportar(conexion)
    conexion.close()
    return nuevos, resumen


if __name__ == "__main__":
    import datetime as dt
    config.entrar_a_datos()
    ids_nuevos, resumen = ingestar(dt.datetime.now().isoformat(timespec="seconds"))
    print(f"Bitácora: {resumen['total_incursiones']} incursiones "
          f"({len(ids_nuevos)} nuevas este ciclo)")
    print(f"Alertas activas (ALTO): {resumen['alertas_activas_ALTO']}")
