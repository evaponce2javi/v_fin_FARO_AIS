"""
FARO AIS CONTINUO — Configuración central
==========================================
Todo lo ajustable del sistema vive aquí. Cambiar el comportamiento
del monitor = editar solo este archivo.

El token NUNCA vive aquí: se lee de la variable de entorno GFW_TOKEN
en tiempo de ejecución (ver obtener_token()).
"""
import os

# ----------------------------------------------------------------------------
# Ritmo del monitoreo
# ----------------------------------------------------------------------------
INTERVALO_HORAS = 6     # cada cuánto consulta el monitor a GFW
                        # (Sentinel-1 revisita cada 6-12 días: consultar más
                        #  seguido no produce datos nuevos, solo gasta cuota)

DIAS_VENTANA = 14       # tamaño de la ventana móvil que se pide en cada ciclo
                        # (amplia a propósito: GFW publica con retraso variable
                        #  y la bitácora idempotente absorbe el solape)

REFRESCO_DASHBOARD_MIN = 5   # cada cuántos minutos se auto-refresca el panel

# ----------------------------------------------------------------------------
# Área de estudio: Región de Valparaíso hasta más allá de las 200 millas
# (mismo rectángulo del proyecto original, Fase 0)
# ----------------------------------------------------------------------------
ZONA_VALPARAISO = {
    "type": "Polygon",
    "coordinates": [[
        [-76.00, -32.00],   # NO (mar afuera, norte)
        [-71.50, -32.00],   # NE (costa, norte)
        [-71.50, -33.80],   # SE (costa, sur)
        [-76.00, -33.80],   # SO (mar afuera, sur)
        [-76.00, -32.00],   # cierre del polígono
    ]],
}

# Línea aproximada de las 5 millas (Fase 0; oficial: Res. 7181/2015)
LON_5_MILLAS = -71.70

# Puertos principales de la región (lat, lon) — para distancia a puerto
PUERTOS = {
    "Valparaíso":  (-33.03, -71.63),
    "San Antonio": (-33.58, -71.62),
    "Quintero":    (-32.77, -71.53),
}

# ----------------------------------------------------------------------------
# Archivos (todos relativos a la carpeta datos/)
# ----------------------------------------------------------------------------
CARPETA_DATOS = "datos"

BASE_DE_DATOS          = "bitacora.db"
ESTADO_DESCARGA        = "estado_descarga.json"
ESTADO_MONITOR         = "estado_monitor.json"
ARCHIVO_NOVEDADES      = "novedades.json"
ARCHIVO_LOG            = "monitor.log"
EXPORT_BITACORA        = "bitacora_export.csv"


def obtener_token():
    """Lee el token de GFW desde la variable de entorno.

    Devuelve None si no está definida — el monitor lo interpreta como
    'modo demo' y trabaja solo con los CSV ya presentes en datos/.
    NUNCA pegar el token en este archivo ni en ningún otro.
    """
    return os.environ.get("GFW_TOKEN")


def entrar_a_datos():
    """Ubica el proceso dentro de la carpeta datos/ (la crea si no existe).

    Todos los scripts trabajan con rutas relativas dentro de datos/;
    esta función es el único lugar donde se resuelve esa ubicación.
    """
    raiz = os.path.dirname(os.path.abspath(__file__))
    carpeta = os.path.join(raiz, CARPETA_DATOS)
    os.makedirs(carpeta, exist_ok=True)
    os.chdir(carpeta)
