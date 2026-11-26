"""
Router — Informe Final del grupo
=================================
Endpoints para que los grupos escriban y envíen su informe de cierre pedagógico,
y para que el docente los consulte todos.

Mecánica "submit-to-unlock":
  - Un grupo puede guardar borradores en cualquier momento (PUT /mi-informe).
  - Solo puede ver los informes de otros grupos DESPUÉS de haber enviado el propio
    (enviado_en IS NOT NULL). Intentar ver antes devuelve 403.
  - El docente (token docente) ve todos los informes sin restricción.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from models import (
    SessionLocal, InformeFinal, Grupo, Instrumento,
    Operacion, Posicion, Configuracion, HistorialCapital
)
from routers.grupos import verificar_token_grupo
from routers.docente import verificar_token_docente

router = APIRouter(prefix="/api/informes", tags=["informes"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Schemas ───────────────────────────────────────────────────────────────────

class InformeUpdate(BaseModel):
    conclusion: Optional[str] = None
    estrategia_descripcion: Optional[str] = None
    decisiones_clave: Optional[str] = None
    que_funcionó: Optional[str] = None
    que_cambiarían: Optional[str] = None
    aprendizaje_principal: Optional[str] = None
    autocalificacion: Optional[int] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _calcular_metricas(db: Session, grupo: Grupo) -> dict:
    """
    Calcula las métricas de cierre del grupo para auto-poblar el informe.
    """
    config = db.query(Configuracion).first()
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    # Capital final = efectivo disponible + valor de mercado de posiciones
    posiciones = db.query(Posicion).filter(
        Posicion.grupo_id == grupo.id,
        Posicion.cantidad > 0
    ).all()
    valor_posiciones = sum(
        p.cantidad * (p.instrumento.precio_actual if p.instrumento else 0)
        for p in posiciones
    )
    capital_final = grupo.capital_disponible + valor_posiciones
    rentabilidad_pct = round((capital_final / capital_inicial - 1) * 100, 2)

    # Operaciones
    ops = db.query(Operacion).filter(Operacion.grupo_id == grupo.id).all()
    n_ops = len(ops)
    n_compras = sum(1 for o in ops if o.tipo == "compra")
    n_ventas = sum(1 for o in ops if o.tipo == "venta")

    # Ticker más operado
    ticker_counts: dict[str, int] = {}
    for o in ops:
        ticker = o.instrumento.ticker if o.instrumento else "?"
        ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1
    ticker_mas_operado = max(ticker_counts, key=ticker_counts.get) if ticker_counts else None

    # Mejor y peor operación de venta (ganancia vs precio promedio de compra)
    mejor = None
    peor = None
    for o in ops:
        if o.tipo != "venta":
            continue
        if not o.instrumento:
            continue
        # Aproximamos ganancia comparando precio de venta vs precio_promedio de la posición actual
        # (es una aproximación; para exactitud necesitaríamos FIFO de compras)
        pos = next((p for p in posiciones if p.instrumento_id == o.instrumento_id), None)
        precio_costo = pos.precio_promedio if pos else o.precio
        if precio_costo and precio_costo > 0:
            ganancia_pct = round((o.precio / precio_costo - 1) * 100, 2)
            entrada = {"ticker": o.instrumento.ticker, "ganancia_pct": ganancia_pct,
                       "fecha": o.timestamp.strftime("%d/%m/%Y")}
            if mejor is None or ganancia_pct > mejor["ganancia_pct"]:
                mejor = entrada
            if peor is None or ganancia_pct < peor["ganancia_pct"]:
                peor = entrada

    # Composición final de cartera
    total_cartera = capital_final or 1.0
    composicion = []
    for p in posiciones:
        if not p.instrumento:
            continue
        valor = p.cantidad * p.instrumento.precio_actual
        composicion.append({
            "ticker": p.instrumento.ticker,
            "nombre": p.instrumento.nombre,
            "valor": round(valor, 2),
            "pct_cartera": round(valor / total_cartera * 100, 1),
        })
    # Agregar efectivo
    pct_efectivo = round(grupo.capital_disponible / total_cartera * 100, 1)
    composicion.append({
        "ticker": "CASH",
        "nombre": "Efectivo disponible",
        "valor": round(grupo.capital_disponible, 2),
        "pct_cartera": pct_efectivo,
    })
    composicion.sort(key=lambda x: x["pct_cartera"], reverse=True)

    # Sectores finales
    sector_valores: dict[str, float] = {}
    for p in posiciones:
        if not p.instrumento:
            continue
        sector = p.instrumento.sector or "Sin sector"
        sector_valores[sector] = sector_valores.get(sector, 0) + p.cantidad * p.instrumento.precio_actual
    sectores = [
        {"sector": s, "valor": round(v, 2), "pct": round(v / total_cartera * 100, 1)}
        for s, v in sorted(sector_valores.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "capital_inicial": capital_inicial,
        "capital_final": round(capital_final, 2),
        "rentabilidad_pct": rentabilidad_pct,
        "n_operaciones": n_ops,
        "n_compras": n_compras,
        "n_ventas": n_ventas,
        "ticker_mas_operado": ticker_mas_operado,
        "mejor_operacion": mejor,
        "peor_operacion": peor,
        "composicion_final": composicion,
        "sectores_finales": sectores,
    }


def _serializar(inf: InformeFinal) -> dict:
    return {
        "id": inf.id,
        "grupo_id": inf.grupo_id,
        "grupo_nombre": inf.grupo.nombre if inf.grupo else None,
        # métricas
        "capital_inicial": inf.capital_inicial,
        "capital_final": inf.capital_final,
        "rentabilidad_pct": inf.rentabilidad_pct,
        "n_operaciones": inf.n_operaciones,
        "n_compras": inf.n_compras,
        "n_ventas": inf.n_ventas,
        "ticker_mas_operado": inf.ticker_mas_operado,
        "mejor_operacion": inf.mejor_operacion,
        "peor_operacion": inf.peor_operacion,
        "composicion_final": inf.composicion_final,
        "sectores_finales": inf.sectores_finales,
        # narrativa
        "conclusion": inf.conclusion,
        "estrategia_descripcion": inf.estrategia_descripcion,
        "decisiones_clave": inf.decisiones_clave,
        "que_funcionó": inf.que_funcionó,
        "que_cambiarían": inf.que_cambiarían,
        "aprendizaje_principal": inf.aprendizaje_principal,
        "autocalificacion": inf.autocalificacion,
        # estado
        "enviado_en": inf.enviado_en.isoformat() if inf.enviado_en else None,
        "creado_en": inf.creado_en.isoformat() if inf.creado_en else None,
    }


# ── Endpoints para grupos ─────────────────────────────────────────────────────

@router.get("/mi-informe")
def obtener_mi_informe(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Devuelve el informe (borrador o enviado) del grupo que hace el request.
    Si no existe, devuelve métricas calculadas al momento y campos vacíos.
    """
    grupo = verificar_token_grupo(authorization, db)
    inf = db.query(InformeFinal).filter(InformeFinal.grupo_id == grupo.id).first()

    if inf:
        return _serializar(inf)

    # Primera vez: calcular métricas y devolver sin persistir (aún no hay borrador)
    metricas = _calcular_metricas(db, grupo)
    return {
        "id": None,
        "grupo_id": grupo.id,
        "grupo_nombre": grupo.nombre,
        **metricas,
        "conclusion": None,
        "estrategia_descripcion": None,
        "decisiones_clave": None,
        "que_funcionó": None,
        "que_cambiarían": None,
        "aprendizaje_principal": None,
        "autocalificacion": None,
        "enviado_en": None,
        "creado_en": None,
    }


@router.put("/mi-informe")
def guardar_borrador(
    body: InformeUpdate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Guarda o actualiza el borrador del informe. No lo envía.
    Se puede llamar múltiples veces — solo actualiza los campos textuales.
    """
    grupo = verificar_token_grupo(authorization, db)
    inf = db.query(InformeFinal).filter(InformeFinal.grupo_id == grupo.id).first()

    if not inf:
        # Crear registro con métricas calculadas
        metricas = _calcular_metricas(db, grupo)
        inf = InformeFinal(grupo_id=grupo.id, **metricas)
        db.add(inf)

    # Actualizar campos textuales
    for field, value in body.dict(exclude_none=True).items():
        setattr(inf, field, value)

    db.commit()
    db.refresh(inf)
    return _serializar(inf)


@router.post("/mi-informe/enviar")
def enviar_informe(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Marca el informe como enviado (enviado_en = now).
    Recalcula métricas al momento del envío y las congela.
    Una vez enviado no se puede modificar.
    """
    grupo = verificar_token_grupo(authorization, db)
    inf = db.query(InformeFinal).filter(InformeFinal.grupo_id == grupo.id).first()

    if inf and inf.enviado_en:
        raise HTTPException(400, "El informe ya fue enviado")

    if not inf:
        metricas = _calcular_metricas(db, grupo)
        inf = InformeFinal(grupo_id=grupo.id, **metricas)
        db.add(inf)
    else:
        # Recalcular métricas al momento del envío
        metricas = _calcular_metricas(db, grupo)
        for k, v in metricas.items():
            setattr(inf, k, v)

    inf.enviado_en = datetime.utcnow()
    db.commit()
    db.refresh(inf)
    return _serializar(inf)


@router.get("/otros")
def ver_otros_informes(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Devuelve los informes enviados de TODOS los grupos, excepto el propio.
    Solo disponible para grupos que ya enviaron su informe (submit-to-unlock).
    """
    grupo = verificar_token_grupo(authorization, db)
    mi_inf = db.query(InformeFinal).filter(InformeFinal.grupo_id == grupo.id).first()

    if not mi_inf or not mi_inf.enviado_en:
        raise HTTPException(
            403,
            "Debés enviar tu informe primero para ver el de los otros grupos"
        )

    otros = (
        db.query(InformeFinal)
        .filter(
            InformeFinal.grupo_id != grupo.id,
            InformeFinal.enviado_en.isnot(None)
        )
        .all()
    )
    return [_serializar(i) for i in otros]


# ── Endpoints para docente ────────────────────────────────────────────────────

@router.get("/docente/todos")
def listar_informes_docente(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """
    Lista todos los informes (borradores + enviados) para el docente.
    Incluye grupos que aún no empezaron su informe (con estado 'pendiente').
    """
    verificar_token_docente(authorization, db)

    grupos = db.query(Grupo).all()
    informes_por_grupo = {
        i.grupo_id: i
        for i in db.query(InformeFinal).all()
    }

    resultado = []
    for g in grupos:
        inf = informes_por_grupo.get(g.id)
        if inf:
            d = _serializar(inf)
            d["estado"] = "enviado" if inf.enviado_en else "borrador"
        else:
            resultado.append({
                "grupo_id": g.id,
                "grupo_nombre": g.nombre,
                "estado": "pendiente",
                "enviado_en": None,
            })
            continue
        resultado.append(d)

    return resultado


@router.get("/docente/{grupo_id}")
def ver_informe_grupo(
    grupo_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """Detalle del informe de un grupo específico — solo docente."""
    verificar_token_docente(authorization, db)
    inf = db.query(InformeFinal).filter(InformeFinal.grupo_id == grupo_id).first()
    if not inf:
        raise HTTPException(404, "El grupo aún no tiene informe")
    return _serializar(inf)
