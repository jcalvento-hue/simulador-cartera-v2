"""
Motor de mercado — random walk persistente
Corre como background task de FastAPI: actualiza precios cada 30 segundos
y guarda el historial en la DB.

Lógica por tipo de instrumento:
- accion / bono / cedear : Geometric Brownian Motion (random walk)
- fci                    : drift puro según TNA configurada (sin volatilidad)
- cauciones              : procesadas al vencer (capital + intereses → capital_disponible)
"""
import asyncio
import random
import math
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import Instrumento, HistorialPrecios, Caucion, Configuracion, Grupo, SessionLocal

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
        _update_prices()
        _procesar_cauciones()


def _update_prices():
    db: Session = SessionLocal()
    try:
        instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
        for inst in instrumentos:
            if inst.tipo == "fci":
                # Drift puro: precio sube continuamente según TNA del fondo
                tna = _FCI_TNA.get(inst.ticker, 0.40)
                factor = math.exp(tna * _INTERVALO_SEG / _SEG_ANUALES)
                nuevo_precio = round(inst.precio_actual * factor, 4)
            else:
                # Geometric Brownian Motion: acciones, bonos, CEDEARs
                sigma = inst.volatilidad
                if sigma == 0:
                    continue
                epsilon = random.gauss(0, 1)
                factor = math.exp(-0.5 * sigma**2 + sigma * epsilon)
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


def generar_historial_inicial(db: Session = None, horas: float = 2.0):
    """
    Genera historial retroactivo para todos los instrumentos activos,
    simulando las últimas `horas` horas con puntos cada 30 segundos.
    Borra el historial existente antes de regenerar (útil al reiniciar simulador).
    Se puede llamar con db externo (desde un router) o abre su propia sesión.
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
        ahora = datetime.utcnow()
        pasos = int(horas * 3600 / _INTERVALO_SEG)   # ej: 2h → 240 pasos

        for inst in instrumentos:
            # Borrar historial previo de este instrumento
            db.query(HistorialPrecios).filter(
                HistorialPrecios.instrumento_id == inst.id
            ).delete()

            # Simular hacia atrás desde el precio actual
            # Reconstruimos la trayectoria partiendo del precio_inicial y
            # avanzando con el mismo GBM/drift, luego ajustamos el precio_actual
            # al final de la trayectoria para mantener coherencia.
            precios = []
            precio = inst.precio_inicial

            for _ in range(pasos):
                if inst.tipo == "fci":
                    tna = _FCI_TNA.get(inst.ticker, 0.40)
                    factor = math.exp(tna * _INTERVALO_SEG / _SEG_ANUALES)
                    precio = round(precio * factor, 4)
                else:
                    sigma = inst.volatilidad
                    if sigma == 0:
                        precios.append(precio)
                        continue
                    epsilon = random.gauss(0, 1)
                    factor = math.exp(-0.5 * sigma**2 + sigma * epsilon)
                    precio = round(precio * factor, 2)
                    precio = max(precio, inst.precio_inicial * 0.20)
                precios.append(precio)

            # Actualizar precio_actual al último precio simulado
            if precios:
                inst.precio_actual = precios[-1]

            # Insertar puntos con timestamps retroactivos
            for i, p in enumerate(precios):
                ts = ahora - timedelta(seconds=_INTERVALO_SEG * (pasos - 1 - i))
                db.add(HistorialPrecios(
                    instrumento_id=inst.id,
                    precio=p,
                    timestamp=ts,
                ))

        db.commit()
        print(f"[market] Historial inicial generado: {pasos} puntos × {len(instrumentos)} instrumentos")
    except Exception as e:
        db.rollback()
        print(f"[market] Error generando historial inicial: {e}")
    finally:
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
