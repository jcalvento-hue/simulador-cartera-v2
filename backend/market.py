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
from datetime import datetime
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
