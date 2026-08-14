"""
FARO AIS CONTINUO — Clasificador de riesgo explicable
======================================================
La MISMA lógica del fase3_riesgo.py original — misma suma de señales,
mismos niveles, mismas señales dormidas (length_m / fishing_score) y la
misma disciplina de no acusar a los oscuros costeros. Se conserva
idéntica a propósito: el puntaje validado con octubre 2025 es el activo
del proyecto; el monitoreo continuo lo envuelve, no lo reescribe.

Lo único que cambia: recibe la ruta del CSV como parámetro (en vez de
iterar ventanas fijas), para que el monitor lo invoque sobre cada
descarga nueva.

DISCIPLINA DE NO SOBREACUSAR
----------------------------
Este clasificador mide OCULTAMIENTO, no nacionalidad ni ilegalidad. Un barco
sin AIS no declara bandera: por construccion el sistema no puede afirmar de
que pais es una deteccion oscura. Y un oscuro costero se limita a VERIFICAR,
porque podria ser un artesanal legitimo. El sistema produce hipotesis
investigables, nunca acusaciones.

Entrada:  sar_detecciones_<sufijo>.csv
Salida:   alertas_<sufijo>.csv   (puntaje 0-100 + razones por detección)
"""
import glob
import math
import os

import pandas as pd

import config


def kilometros(lat1, lon1, lat2, lon2):
    """Distancia Haversine en km entre dos coordenadas."""
    radio_tierra = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    a = math.sin(delta_lat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(delta_lon / 2) ** 2
    return 2 * radio_tierra * math.asin(math.sqrt(a))


def clasificar_archivo(ruta_sar):
    """Clasifica un CSV de detecciones SAR. Devuelve el n° de alertas (o None)."""
    if not os.path.exists(ruta_sar) or os.path.getsize(ruta_sar) < 10:
        return None

    detecciones = pd.read_csv(ruta_sar)
    if detecciones.empty or "mmsi" not in detecciones.columns:
        return None

    # Los vacíos pueden llegar como "" (string) en vez de nulo: normalizar
    detecciones["mmsi"] = detecciones["mmsi"].replace("", pd.NA)
    detecciones["oscuro"] = detecciones["mmsi"].isna()

    # --- señales por detección ---
    detecciones["zona"] = detecciones["lon"].apply(
        lambda lon: "dentro_5_millas" if lon > config.LON_5_MILLAS else "ZEE_interior")
    detecciones["dist_puerto_km"] = detecciones.apply(
        lambda fila: min(kilometros(fila.lat, fila.lon, lat_p, lon_p)
                         for lat_p, lon_p in config.PUERTOS.values()),
        axis=1).round(1)
    detecciones["celda"] = (detecciones.lat.round(2).astype(str) + ","
                            + detecciones.lon.round(2).astype(str))
    fechas_por_celda = detecciones[detecciones.oscuro].groupby("celda")["date"].nunique()
    detecciones["persistencia"] = detecciones["celda"].map(fechas_por_celda).fillna(0).astype(int)
    oscuros_por_dia = detecciones[detecciones.oscuro].groupby("date")["celda"].count()
    detecciones["grupo_dia"] = detecciones["date"].map(oscuros_por_dia).fillna(0).astype(int)

    # --- puntaje explicable: cada punto lleva su razón en texto ---
    def puntuar(fila):
        if not fila.oscuro:
            return 0, "transmite AIS: en regla"
        puntos, razones = 30, ["sin señal AIS (radar sí lo detecta): +30"]
        if fila.zona == "ZEE_interior":
            puntos += 25; razones.append("en ZEE interior, fuera de franja costera: +25")
        else:
            puntos += 10; razones.append("dentro de 5 millas (posible artesanal sin AIS): +10")
        if fila.dist_puerto_km > 30:
            puntos += 15; razones.append(f"lejos de puerto ({fila.dist_puerto_km} km): +15")
        if fila.persistencia >= 2:
            puntos += 15; razones.append(
                f"presencia repetida en la misma celda ({fila.persistencia} fechas): +15")
        if fila.grupo_dia >= 3:
            puntos += 10; razones.append(f"opera en grupo ({fila.grupo_dia} oscuros ese día): +10")
        # señales opcionales si el dataset las trae (Data Download Portal)
        if "length_m" in fila and pd.notna(fila.get("length_m")):
            if fila.length_m >= 25:
                puntos += 20; razones.append(f"tamaño industrial ({fila.length_m:.0f} m): +20")
                if fila.zona == "dentro_5_millas":
                    puntos = max(puntos, 95)
                    razones.append("industrial DENTRO de reserva artesanal: crítico")
            else:
                puntos -= 15; razones.append(f"embarcación menor ({fila.length_m:.0f} m): -15")
        if ("fishing_score" in fila and pd.notna(fila.get("fishing_score"))
                and fila.fishing_score >= 0.7):
            puntos += 10; razones.append(f"IA de GFW: prob. de faena {fila.fishing_score:.0%}: +10")
        # --- TOPE DE CONTENCIÓN: no acusar a quien no podemos acusar ---
        # Un oscuro dentro de las 5 millas puede ser un artesanal legítimo que
        # simplemente no lleva AIS. Sin el dato de eslora no hay forma de
        # distinguirlo, así que su puntaje se limita a VERIFICAR (44): queda
        # registrado para revisión humana, pero el sistema nunca lo eleva a
        # alerta. La única excepción es que el dataset confirme tamaño
        # industrial, caso en que la ley (Art. 47) es inequívoca y el bloque
        # de length_m de más arriba ya lo marcó como crítico.
        industrial_confirmado = ("length_m" in fila and pd.notna(fila.get("length_m"))
                                 and fila.length_m >= 25)
        if fila.zona == "dentro_5_millas" and not industrial_confirmado and puntos > 44:
            puntos = 44
            razones.append("tope de contención: costero sin eslora confirmada "
                           "→ se limita a VERIFICAR, no se acusa")
        return min(puntos, 100), " | ".join(razones)

    resultado = detecciones.apply(puntuar, axis=1, result_type="expand")
    detecciones["puntaje"], detecciones["razones"] = resultado[0], resultado[1]
    detecciones["nivel"] = pd.cut(detecciones.puntaje, [-1, 24, 44, 69, 100],
                                  labels=["BAJO", "VERIFICAR", "MEDIO", "ALTO"])

    alertas = detecciones[detecciones.oscuro].sort_values("puntaje", ascending=False)[
        ["date", "lat", "lon", "zona", "dist_puerto_km",
         "persistencia", "grupo_dia", "puntaje", "nivel", "razones"]]

    sufijo = os.path.basename(ruta_sar).replace("sar_detecciones_", "").replace(".csv", "")
    ruta_salida = f"alertas_{sufijo}.csv"
    alertas.to_csv(ruta_salida, index=False)
    print(f"[{sufijo}] {len(alertas)} alertas -> {ruta_salida} "
          f"| niveles: {alertas.nivel.value_counts().to_dict()}")
    return len(alertas)


def procesar_todo():
    """Clasifica todos los CSV de SAR presentes en datos/. Idempotente:
    reclasificar un archivo ya visto produce el mismo resultado, y la
    bitácora (motor.py) descarta los duplicados por ID estable."""
    total = 0
    for ruta in sorted(glob.glob("sar_detecciones_*.csv")):
        cantidad = clasificar_archivo(ruta)
        if cantidad:
            total += cantidad
    return total


if __name__ == "__main__":
    config.entrar_a_datos()
    procesar_todo()
