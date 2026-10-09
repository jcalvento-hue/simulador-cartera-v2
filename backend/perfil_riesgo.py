"""
Lógica de perfil de riesgo:
- Encuesta de 6 preguntas
- Puntaje → Conservador / Moderado / Agresivo
- Validación de coherencia operación ↔ perfil
"""

PREGUNTAS = [
    {
        "num": 1,
        "texto": "¿Cuál es el principal objetivo de esta inversión?",
        "opciones": {
            "a": {"texto": "Preservar el capital y no perder dinero", "puntaje": 1},
            "b": {"texto": "Obtener rendimientos moderados asumiendo algún riesgo", "puntaje": 2},
            "c": {"texto": "Maximizar el retorno aunque implique alta volatilidad", "puntaje": 3},
        }
    },
    {
        "num": 2,
        "texto": "¿Qué harías si tu cartera cae un 20% en un mes?",
        "opciones": {
            "a": {"texto": "Vendo todo para evitar pérdidas mayores", "puntaje": 1},
            "b": {"texto": "Espero a que se recupere sin hacer cambios", "puntaje": 2},
            "c": {"texto": "Compro más aprovechando el precio bajo", "puntaje": 3},
        }
    },
    {
        "num": 3,
        "texto": "¿Con qué frecuencia planeás revisar y operar tu cartera?",
        "opciones": {
            "a": {"texto": "Poco — prefiero una estrategia de largo plazo sin cambios frecuentes", "puntaje": 1},
            "b": {"texto": "Mensualmente o ante eventos importantes", "puntaje": 2},
            "c": {"texto": "Diariamente, siguiendo las noticias y movimientos del mercado", "puntaje": 3},
        }
    },
    {
        "num": 4,
        "texto": "¿Cuál de estas carteras preferirías?",
        "opciones": {
            "a": {"texto": "Una que rinda 5% anual con mínima variación", "puntaje": 1},
            "b": {"texto": "Una que rinda entre -5% y +20% según el año", "puntaje": 2},
            "c": {"texto": "Una que pueda rendir +50% o perder -30% según el mercado", "puntaje": 3},
        }
    },
    {
        "num": 5,
        "texto": "¿Qué porcentaje de tu capital invertirías en acciones de alta volatilidad?",
        "opciones": {
            "a": {"texto": "Menos del 20%", "puntaje": 1},
            "b": {"texto": "Entre el 20% y el 60%", "puntaje": 2},
            "c": {"texto": "Más del 60%", "puntaje": 3},
        }
    },
    {
        "num": 6,
        "texto": "Ante una noticia negativa sobre una empresa de tu cartera, ¿qué hacés?",
        "opciones": {
            "a": {"texto": "Vendo inmediatamente para limitar pérdidas", "puntaje": 1},
            "b": {"texto": "Analizo si el impacto es permanente antes de decidir", "puntaje": 2},
            "c": {"texto": "Mantengo o compro más si creo en la empresa a largo plazo", "puntaje": 3},
        }
    },
]

# Umbrales de puntaje (suma de 6 preguntas, min 6, max 18)
PERFILES = {
    "conservador": (6, 10),
    "moderado":    (11, 14),
    "agresivo":    (15, 18),
}


def calcular_perfil(respuestas: dict) -> tuple[str, int]:
    """
    respuestas: {1: 'a', 2: 'c', ...}
    Retorna (perfil, puntaje_total)
    """
    total = 0
    for pregunta in PREGUNTAS:
        num = pregunta["num"]
        resp = respuestas.get(str(num)) or respuestas.get(num)
        if resp and resp in pregunta["opciones"]:
            total += pregunta["opciones"][resp]["puntaje"]

    if total <= 10:
        perfil = "conservador"
    elif total <= 14:
        perfil = "moderado"
    else:
        perfil = "agresivo"

    return perfil, total


# ── Validación de coherencia operación ↔ perfil ──────────────────────────────

# Volatilidad máxima tolerada por perfil
TOLERANCIA_VOLATILIDAD = {
    "conservador": 0.015,   # solo activos de baja vol
    "moderado":    0.028,   # activos de vol media
    "agresivo":    1.0,     # sin restricción
}

# Exposición máxima en un solo activo (% del capital total del grupo)
EXPOSICION_MAX = {
    "conservador": 0.20,
    "moderado":    0.40,
    "agresivo":    1.0,
}


def validar_coherencia(
    perfil: str,
    volatilidad_instrumento: float,
    monto_operacion: float,
    capital_total: float,      # efectivo + valor cartera
) -> tuple[bool, str]:
    """
    Retorna (es_coherente, mensaje_advertencia)
    Si es_coherente=True → sin advertencia
    Si es_coherente=False → mostrar advertencia pero permitir confirmar
    """
    mensajes = []

    # Verificar volatilidad
    vol_max = TOLERANCIA_VOLATILIDAD.get(perfil, 1.0)
    if volatilidad_instrumento > vol_max:
        mensajes.append(
            f"Este activo tiene una volatilidad de {volatilidad_instrumento*100:.1f}%, "
            f"mayor a la tolerada para un perfil {perfil} ({vol_max*100:.1f}%)."
        )

    # Verificar concentración
    exp_max = EXPOSICION_MAX.get(perfil, 1.0)
    exposicion = monto_operacion / capital_total if capital_total > 0 else 0
    if exposicion > exp_max:
        mensajes.append(
            f"Esta operación representa el {exposicion*100:.1f}% de tu capital total, "
            f"superando el límite recomendado para un perfil {perfil} ({exp_max*100:.1f}%)."
        )

    if mensajes:
        advertencia = (
            f"⚠️ Advertencia de perfil ({perfil.upper()}): " + " ".join(mensajes) +
            " Podés confirmar igualmente, pero queda registrado."
        )
        return False, advertencia

    return True, ""
