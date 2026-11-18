"""
Motor de mercado — random walk persistente
Corre como background task de FastAPI: actualiza precios cada 30 segundos
y guarda el historial en la DB.

Lógica por tipo de instrumento:
- accion / bono / cedear : Geometric Brownian Motion (random walk)
- fci                    : drift puro según TNA configurada (sin volatilidad)
- cauciones              : procesadas al vencer (capital + intereses → capital_disponible)

Al regenerar historial:
- Los precios reales se reciben desde el frontend (browser) vía set-precios
- El GBM arranca desde precio_actual (ya seteado con el precio real)
- historial_real.py ya no se llama desde aquí (Render bloquea outbound HTTP)
"""
import asyncio
import random
import math
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from models import Instrumento, HistorialPrecios, Caucion, Configuracion, Grupo, SessionLocal

# Flag para pausar el random walk mientras se regenera el historial
# (evita SQLite "database is locked" por escrituras simultáneas)
_regenerando = False

# TNA por tipo de FCI (anual) — base que se usa si no hay config
_FCI_TNA = {
    "FCICONV": 0.37,   # Money Market conservador
    "FCIMOD":  0.45,   # Renta Fija moderado
    "FCIAGR":  0.60,   # Renta Variable agresivo
}

# El loop corre cada 30 segundos — calculamos cuánto corresponde de drift
_INTERVALO_SEG = 30
_SEG_ANUALES   = 365 * 24 * 3600


async def random_walk_loop():
    """Loop infinito que actualiza precios y procesa cauciones cada 30 segundos."""
    while True:
        await asyncio.sleep(_INTERVALO_SEG)
        if _regenerando:
            print("[market] random_walk_loop: pausado mientras se regenera historial", flush=True)
            continue
        _update_prices()
        _procesar_cauciones()


def _calcular_mu(inst: "Instrumento", config: "Configuracion") -> float:
    """
    Deriva el drift continuo (mu) por intervalo de 30 segundos a partir de la
    tendencia_esperada (% total al vencimiento) y las fechas de inicio/fin.

    Si no hay tendencia configurada, o faltan fechas, mu = 0 (puro random walk).
    La fórmula es: mu = ln(1 + tendencia) / N_intervalos
    donde N_intervalos = duración_total_segundos / 30.
    """
    if inst.tendencia_esperada is None:
        return 0.0
    if config is None or config.fecha_inicio is None or config.fecha_fin is None:
        return 0.0
    duracion_seg = (config.fecha_fin - config.fecha_inicio).total_seconds()
    if duracion_seg <= 0:
        return 0.0
    n_intervalos = duracion_seg / _INTERVALO_SEG
    # mu por intervalo: ln(1 + pct_total) / n_intervalos
    return math.log(1.0 + inst.tendencia_esperada) / n_intervalos


def _update_prices():
    db: Session = SessionLocal()
    try:
        config = db.query(Configuracion).first()
        instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
        for inst in instrumentos:
            if inst.tipo == "fci":
                # Drift puro: precio sube continuamente según TNA del fondo
                tna = _FCI_TNA.get(inst.ticker, 0.40)
                factor = math.exp(tna * _INTERVALO_SEG / _SEG_ANUALES)
                nuevo_precio = round(inst.precio_actual * factor, 4)
            else:
                # Geometric Brownian Motion con drift de tendencia esperada
                sigma = inst.volatilidad
                if sigma == 0:
                    continue
                mu = _calcular_mu(inst, config)
                epsilon = random.gauss(0, 1)
                # GBM con drift: exp((mu - 0.5*sigma²) + sigma*ε)
                factor = math.exp((mu - 0.5 * sigma**2) + sigma * epsilon)
                nuevo_precio = round(inst.precio_actual * factor, 2)
                # Floor: no puede caer más del 80% del inicial
                nuevo_precio = max(nuevo_precio, inst.precio_inicial * 0.20)

            inst.precio_actual = nuevo_precio
            db.add(HistorialPrecios(
                instrumento_id=inst.id,
                precio=nuevo_precio,
                timestamp=datetime.utcnow()
            ))
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[market] Error actualizando precios: {e}")
    finally:
        db.close()


def _procesar_cauciones():
    """Acredita cauciones vencidas al capital disponible del grupo."""
    db: Session = SessionLocal()
    try:
        ahora = datetime.utcnow()
        vencidas = (
            db.query(Caucion)
            .filter(Caucion.cobrada == False, Caucion.vence_en <= ahora)
            .all()
        )
        for c in vencidas:
            grupo = db.query(Grupo).filter(Grupo.id == c.grupo_id).first()
            if grupo:
                grupo.capital_disponible += c.monto_total
                c.cobrada = True
                print(f"[market] Caución #{c.id} vencida — grupo {grupo.nombre} +${c.monto_total:,.2f}")
        if vencidas:
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"[market] Error procesando cauciones: {e}")
    finally:
        db.close()


def _gbm_retroactivo(precio_actual: float, pasos: int, sigma_por_paso: float,
                      tipo: str, ticker: str, precio_inicial: float) -> list:
    """
    Genera una lista de precios GBM retroactivos (de más viejo a más nuevo).
    El último elemento es precio_actual.
    sigma_por_paso: volatilidad normalizada al intervalo del paso.
    """
    precio = precio_actual
    precios = [precio]
    for _ in range(pasos - 1):
        if tipo == "fci":
            tna = _FCI_TNA.get(ticker, 0.40)
            # Para FCI retroactivo usamos el intervalo normalizado dado
            factor = math.exp(-tna * sigma_por_paso / _SEG_ANUALES)
            precio = round(precio * factor, 4)
        else:
            if sigma_por_paso == 0:
                precios.insert(0, precio)
                continue
            epsilon = random.gauss(0, 1)
            factor = math.exp(-0.5 * sigma_por_paso**2 + sigma_por_paso * epsilon)
            precio = round(precio * factor, 2)
            precio = max(precio, precio_inicial * 0.20)
        precios.insert(0, precio)
    return precios


def generar_historial_inicial(db: Session = None, horas: float = 2.0):
    """
    Regenera el historial GBM completo para todos los instrumentos activos.

    Genera tres capas de puntos históricos simulados:
    - Sesión (últimas 2h): punto cada 30s — para gráfico intradiario
    - Semana (últimos 7d): punto cada 15min — para vista 1S
    - Mes   (últimos 30d): punto cada 1h  — para vista 1M
    - Año   (últimos 365d): punto por día — para vista 1A

    Los precios reales ya fueron seteados previamente por set-precios.
    No intenta descargar precios de internet (Render bloquea outbound HTTP).
    """
    global _regenerando
    _regenerando = True
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
        ahora = datetime.utcnow()

        # ── Configuración de capas históricas ─────────────────────────────────
        # (intervalo_seg, dias_atras, sigma_escala)
        # sigma_escala = sqrt(intervalo / seg_por_dia) normaliza la vol diaria al intervalo
        SEG_DIA = 86400
        capas = [
            # (nombre,  intervalo_seg, dias,  sigma_escala)
            ("sesion",  _INTERVALO_SEG,    horas / 24,  math.sqrt(_INTERVALO_SEG / SEG_DIA)),
            ("semana",  15 * 60,           7,           math.sqrt(15 * 60 / SEG_DIA)),
            ("mes",     3600,              30,          math.sqrt(3600 / SEG_DIA)),
            ("anio",    SEG_DIA,           365,         1.0),   # vol diaria directa
        ]

        for inst in instrumentos:
            # Borrar historial previo
            db.query(HistorialPrecios).filter(
                HistorialPrecios.instrumento_id == inst.id
            ).delete()

            # Sincronizar precio_sesion con precio_actual
            inst.precio_sesion = inst.precio_actual

            total_puntos = 0
            precio_capa = inst.precio_actual   # cada capa arranca desde el precio_actual

            for nombre, intervalo, dias, sigma_esc in capas:
                pasos = max(2, int(dias * SEG_DIA / intervalo))
                sigma_paso = inst.volatilidad * sigma_esc if inst.tipo != "fci" else intervalo

                precios_capa = _gbm_retroactivo(
                    precio_actual=precio_capa,
                    pasos=pasos,
                    sigma_por_paso=sigma_paso,
                    tipo=inst.tipo,
                    ticker=inst.ticker,
                    precio_inicial=inst.precio_inicial,
                )

                for i, p in enumerate(precios_capa):
                    ts = ahora - timedelta(seconds=intervalo * (len(precios_capa) - 1 - i))
                    db.add(HistorialPrecios(
                        instrumento_id=inst.id,
                        precio=p,
                        timestamp=ts,
                    ))

                total_puntos += len(precios_capa)
                # La próxima capa más vieja arranca desde el precio más viejo de esta capa
                precio_capa = precios_capa[0]

            print(f"[market] {inst.ticker}: precio_actual={inst.precio_actual:.2f}, {total_puntos} puntos GBM (sesion+semana+mes+anio)", flush=True)

        db.commit()
        print(f"[market] Historial regenerado para {len(instrumentos)} instrumentos", flush=True)
    except Exception as e:
        db.rollback()
        print(f"[market] Error generando historial inicial: {e}", flush=True)
    finally:
        _regenerando = False
        if close_db:
            db.close()


def get_precio_actual(db: Session, instrumento_id: int) -> float:
    inst = db.query(Instrumento).filter(Instrumento.id == instrumento_id).first()
    return inst.precio_actual if inst else 0.0


def get_historial(db: Session, instrumento_id: int, limit: int = 100):
    return (
        db.query(HistorialPrecios)
        .filter(HistorialPrecios.instrumento_id == instrumento_id)
        .order_by(HistorialPrecios.timestamp.desc())
        .limit(limit)
        .all()
    )
