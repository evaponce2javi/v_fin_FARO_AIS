"""
FARO AIS CONTINUO — Descarga incremental (ventana móvil)
=========================================================
Reemplazo del fase1_descarga.py original. La diferencia clave: en lugar
de tres ventanas históricas fijas, cada ejecución calcula una ventana
móvil (hoy - DIAS_VENTANA -> hoy) y descarga solo ese rango.

Mantiene estado_descarga.json con la última consulta exitosa: si un
ciclo falla (sin red, API caída, pipeline SAR en mantención), el
siguiente ciclo recupera el rango pendiente sin dejar huecos.

Los CSV descargados llevan sufijo de fecha (sar_detecciones_2026-08-09.csv)
y nunca se sobreescriben: son la evidencia cruda.

Uso directo (un ciclo de descarga, requiere GFW_TOKEN):
    python descarga_incremental.py
"""
import asyncio
import datetime as dt
import json
import os

import pandas as pd

import config


class SinToken(Exception):
    """No hay GFW_TOKEN en el entorno: el monitor pasa a modo demo."""


def _leer_estado():
    if os.path.exists(config.ESTADO_DESCARGA):
        with open(config.ESTADO_DESCARGA, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _guardar_estado(estado):
    with open(config.ESTADO_DESCARGA, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=2)


def calcular_ventana(hoy=None):
    """Ventana a pedir en este ciclo.

    Parte en (hoy - DIAS_VENTANA), pero si la última descarga exitosa es
    más antigua que eso, retrocede hasta ella: así un monitor que estuvo
    apagado una semana recupera el hueco completo al volver.
    """
    hoy = hoy or dt.date.today()
    inicio_normal = hoy - dt.timedelta(days=config.DIAS_VENTANA)

    estado = _leer_estado()
    ultima = estado.get("ultima_descarga_exitosa")
    if ultima:
        ultima_fecha = dt.date.fromisoformat(ultima[:10])
        inicio = min(inicio_normal, ultima_fecha)
    else:
        inicio = inicio_normal

    return inicio.isoformat(), hoy.isoformat()


async def _descargar(fecha_inicio, fecha_fin):
    """Pide a GFW las detecciones SAR + gap events de la ventana."""
    token = config.obtener_token()
    if not token:
        raise SinToken(
            "Falta GFW_TOKEN. Exporta la variable de entorno:\n"
            '  Linux/Mac:  export GFW_TOKEN="tu_token"\n'
            "  Windows:    set GFW_TOKEN=tu_token"
        )

    import gfwapiclient  # import tardío: el modo demo no necesita la librería

    cliente = gfwapiclient.Client(access_token=token)
    sufijo = fecha_fin  # los archivos quedan marcados con la fecha del ciclo
    archivos = []

    # ---- 1) Detecciones SAR (el corazón: incluye barcos SIN AIS) ----------
    reporte_sar = await cliente.fourwings.create_sar_presence_report(
        spatial_resolution="HIGH",
        temporal_resolution="DAILY",
        group_by="VESSEL_ID",
        start_date=fecha_inicio,
        end_date=fecha_fin,
        geojson=config.ZONA_VALPARAISO,
    )
    df_sar = reporte_sar.df()
    ruta_sar = f"sar_detecciones_{sufijo}.csv"
    df_sar.to_csv(ruta_sar, index=False)
    archivos.append(ruta_sar)
    print(f"  SAR: {len(df_sar)} filas -> {ruta_sar}")

    # ---- 2) Apagados intencionales de AIS (señal complementaria) ----------
    try:
        eventos = await cliente.events.get_all_events(
            datasets=["public-global-gaps-events:latest"],
            start_date=fecha_inicio,
            end_date=fecha_fin,
            geometry=config.ZONA_VALPARAISO,
            limit=1000,
        )
        df_eventos = eventos.df()
        ruta_eventos = f"eventos_apagado_ais_{sufijo}.csv"
        df_eventos.to_csv(ruta_eventos, index=False)
        archivos.append(ruta_eventos)
        print(f"  Apagados AIS: {len(df_eventos)} eventos -> {ruta_eventos}")
    except Exception as error:  # los gaps son bonus: si fallan, no frenan el ciclo
        print(f"  Apagados AIS: no disponibles ({type(error).__name__}: {error})")

    return archivos


def descargar_ciclo():
    """Punto de entrada del monitor. Devuelve la lista de archivos nuevos.

    Lanza SinToken si no hay credencial (modo demo) y propaga cualquier
    otro error de red/API para que el monitor lo registre y reintente.
    """
    fecha_inicio, fecha_fin = calcular_ventana()
    print(f"Ventana móvil: {fecha_inicio} -> {fecha_fin}")

    archivos = asyncio.run(_descargar(fecha_inicio, fecha_fin))

    estado = _leer_estado()
    estado["ultima_descarga_exitosa"] = dt.datetime.now().isoformat(timespec="seconds")
    estado["ultima_ventana"] = [fecha_inicio, fecha_fin]
    _guardar_estado(estado)
    return archivos


if __name__ == "__main__":
    config.entrar_a_datos()
    descargar_ciclo()
