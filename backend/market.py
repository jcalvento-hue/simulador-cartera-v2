"""
Motor de mercado — random walk persistente
Corre como background task de FastAPI: actualiza precios cada 30 segundos
y guarda el historial en la DB.
"""
import asyncio
import random
import math
from datetime import datetime
from sqlalchemy.orm import Session
from models import Instrumento, HistorialPrecios, SessionLocal


async def random_walk_loop():
    """Loop infinito que actualiza precios cada 30 segundos."""
    while True:
        await asyncio.sleep(30)
        _update_prices()


def _update_prices():
    db: Session = SessionLocal()
    try:
        instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
        for inst in instrumentos:
            # Geometric Brownian Motion simplificado
            # mu = 0 (sin drift), sigma = volatilidad del instrumento
            sigma = inst.volatilidad
            epsilon = random.gauss(0, 1)
            factor = math.exp(-0.5 * sigma**2 + sigma * epsilon)
            nuevo_precio = round(inst.precio_actual * factor, 2)
            # Floor: el precio no puede caer más del 80% del inicial
            nuevo_precio = max(nuevo_precio, inst.precio_inicial * 0.20)

            inst.precio_actual = nuevo_precio

            # Guardar en historial
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
