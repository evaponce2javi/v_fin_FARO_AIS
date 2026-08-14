"""
FARO AIS CONTINUO — Monitor (scheduler)
========================================
El corazón del cambio batch -> continuo. Un bucle en Python puro
(sin cron, sin Celery: la herramienta más simple que resuelve el
problema) que cada INTERVALO_HORAS:

  1. Descarga la ventana móvil desde GFW (descarga_incremental).
  2. Clasifica lo descargado (riesgo).
  3. Lo ingresa a la bitácora idempotente (motor).
  4. Si hay incursiones NUEVAS de nivel ALTO, las publica en novedades.json.
  5. Registra el ciclo en monitor.log y actualiza estado_monitor.json
     (la marca de "última actualización" que muestra el dashboard).

Manejo de errores deliberadamente conservador: un ciclo que falla se
anota y se reintenta al siguiente; el monitor NUNCA se cae por un error
de red o de la API. Sin GFW_TOKEN corre en "modo demo" sobre los CSV
ya presentes en datos/.

Uso:
    python monitor.py             # queda corriendo, un ciclo cada 6 h
    python monitor.py --una-vez   # un solo ciclo (útil para probar)
"""
import datetime as dt
import json
import sqlite3
import sys
import time
import traceback

import config
import descarga_incremental
import motor
import riesgo


def _anotar_log(mensaje):
    marca = dt.datetime.now().isoformat(timespec="seconds")
    linea = f"[{marca}] {mensaje}"
    print(linea)
    with open(config.ARCHIVO_LOG, "a", encoding="utf-8") as archivo:
        archivo.write(linea + "\n")


def _publicar_novedades(ids_nuevos):
    """Escribe en novedades.json las incursiones ALTO nuevas del ciclo."""
    if not ids_nuevos:
        novedades = []
    else:
        conexion = sqlite3.connect(config.BASE_DE_DATOS)
        conexion.row_factory = sqlite3.Row
        marcadores = ",".join("?" * len(ids_nuevos))
        novedades = [dict(fila) for fila in conexion.execute(
            f"SELECT * FROM incursiones WHERE id IN ({marcadores}) AND nivel='ALTO' "
            "ORDER BY puntaje DESC", ids_nuevos)]
        conexion.close()
    with open(config.ARCHIVO_NOVEDADES, "w", encoding="utf-8") as archivo:
        json.dump(novedades, archivo, ensure_ascii=False, indent=2)
    return len(novedades)


def _guardar_estado_monitor(resultado):
    with open(config.ESTADO_MONITOR, "w", encoding="utf-8") as archivo:
        json.dump(resultado, archivo, ensure_ascii=False, indent=2)


def ciclo():
    """Un ciclo completo del monitor. Nunca lanza excepciones hacia afuera."""
    inicio = dt.datetime.now()
    resultado = {
        "ultima_actualizacion": inicio.isoformat(timespec="seconds"),
        "proximo_ciclo": (inicio + dt.timedelta(hours=config.INTERVALO_HORAS)
                          ).isoformat(timespec="seconds"),
        "intervalo_horas": config.INTERVALO_HORAS,
        "modo": "en_vivo",
        "descarga_ok": False,
        "nuevas_incursiones": 0,
        "nuevas_alertas_alto": 0,
        "error": None,
    }

    # --- 1) Descargar (o modo demo si no hay token) -------------------------
    try:
        archivos = descarga_incremental.descargar_ciclo()
        resultado["descarga_ok"] = True
        _anotar_log(f"descarga OK: {len(archivos)} archivo(s) nuevos")
    except descarga_incremental.SinToken:
        resultado["modo"] = "demo"
        _anotar_log("sin GFW_TOKEN: modo demo sobre los CSV existentes en datos/")
    except Exception as error:
        resultado["error"] = f"descarga: {type(error).__name__}: {error}"
        _anotar_log(f"descarga FALLÓ ({resultado['error']}); "
                    "se continúa con los datos existentes y se reintenta al próximo ciclo")

    # --- 2) Clasificar + 3) ingresar a bitácora -----------------------------
    try:
        riesgo.procesar_todo()
        ids_nuevos, resumen = motor.ingestar(resultado["ultima_actualizacion"])
        resultado["nuevas_incursiones"] = len(ids_nuevos)
        # --- 4) Novedades: lo ALTO que no estaba antes ----------------------
        resultado["nuevas_alertas_alto"] = _publicar_novedades(ids_nuevos)
        _anotar_log(
            f"ciclo OK: {resultado['nuevas_incursiones']} incursiones nuevas "
            f"({resultado['nuevas_alertas_alto']} ALTO) · "
            f"bitácora total: {resumen['total_incursiones']}")
    except Exception as error:
        resultado["error"] = f"pipeline: {type(error).__name__}: {error}"
        _anotar_log(f"pipeline FALLÓ: {resultado['error']}")
        _anotar_log(traceback.format_exc().strip().splitlines()[-1])

    # --- 5) Estado para el banner del dashboard -----------------------------
    _guardar_estado_monitor(resultado)
    return resultado


def correr_para_siempre():
    _anotar_log(f"monitor iniciado: un ciclo cada {config.INTERVALO_HORAS} h "
                f"(Ctrl+C para detener)")
    while True:
        ciclo()
        time.sleep(config.INTERVALO_HORAS * 3600)


if __name__ == "__main__":
    config.entrar_a_datos()
    if "--una-vez" in sys.argv:
        ciclo()
    else:
        try:
            correr_para_siempre()
        except KeyboardInterrupt:
            _anotar_log("monitor detenido por el usuario")
