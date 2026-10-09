"""Router de grupos — cartera, operaciones, encuesta, noticias, ranking"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta
from models import (
    Grupo, Instrumento, Posicion, Operacion, Noticia,
    LecturaNoticia, RespuestaEncuesta, Configuracion, Caucion, get_db
)
from auth import get_current_grupo
from perfil_riesgo import PREGUNTAS, calcular_perfil, validar_coherencia

router = APIRouter(prefix="/api/grupos", tags=["grupos"])


# ── Encuesta de perfil de riesgo ─────────────────────────────────────────────

@router.get("/encuesta/preguntas")
def get_preguntas():
    return PREGUNTAS


class EncuestaIn(BaseModel):
    respuestas: dict   # {"1": "a", "2": "c", ...}


@router.post("/encuesta")
def completar_encuesta(
    body: EncuestaIn,
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    if grupo.encuesta_completada:
        return {"perfil": grupo.perfil_riesgo, "ya_completada": True}

    perfil, puntaje = calcular_perfil(body.respuestas)

    # Guardar respuestas individuales
    for pregunta in PREGUNTAS:
        num = pregunta["num"]
        resp = body.respuestas.get(str(num))
        if resp:
            puntaje_resp = pregunta["opciones"].get(resp, {}).get("puntaje", 0)
            db.add(RespuestaEncuesta(
                grupo_id=grupo.id,
                pregunta_num=num,
                respuesta=resp,
                puntaje=puntaje_resp,
            ))

    grupo.perfil_riesgo = perfil
    grupo.encuesta_completada = True
    db.commit()

    return {"perfil": perfil, "puntaje": puntaje}


# ── Mercado ───────────────────────────────────────────────────────────────────

@router.get("/mercado")
def get_mercado(db: Session = Depends(get_db), _=Depends(get_current_grupo)):
    instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).all()
    return [
        {
            "id": i.id,
            "ticker": i.ticker,
            "nombre": i.nombre,
            "tipo": i.tipo,
            "precio_actual": i.precio_actual,
            "precio_inicial": i.precio_inicial,
            "variacion_pct": round((i.precio_actual - i.precio_inicial) / i.precio_inicial * 100, 2),
            "volatilidad": i.volatilidad,
        }
        for i in instrumentos
    ]


@router.get("/mercado/{ticker}/historial")
def get_historial(ticker: str, db: Session = Depends(get_db), _=Depends(get_current_grupo)):
    inst = db.query(Instrumento).filter(Instrumento.ticker == ticker.upper()).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado")
    from models import HistorialPrecios
    precios = (
        db.query(HistorialPrecios)
        .filter(HistorialPrecios.instrumento_id == inst.id)
        .order_by(HistorialPrecios.timestamp.asc())
        .limit(200)
        .all()
    )
    return {
        "ticker": inst.ticker,
        "precios": [{"t": p.timestamp.isoformat(), "p": p.precio} for p in precios]
    }


# ── Cartera ───────────────────────────────────────────────────────────────────

@router.get("/cartera")
def get_cartera(db: Session = Depends(get_db), grupo: Grupo = Depends(get_current_grupo)):
    config = db.query(Configuracion).first()
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    posiciones = [
        {
            "instrumento_id": p.instrumento_id,
            "ticker": p.instrumento.ticker,
            "nombre": p.instrumento.nombre,
            "cantidad": p.cantidad,
            "precio_actual": p.instrumento.precio_actual,
            "precio_promedio": p.precio_promedio,
            "valor_mercado": round(p.cantidad * p.instrumento.precio_actual, 2),
            "resultado": round((p.instrumento.precio_actual - p.precio_promedio) * p.cantidad, 2),
            "resultado_pct": round(
                (p.instrumento.precio_actual - p.precio_promedio) / p.precio_promedio * 100
                if p.precio_promedio > 0 else 0, 2
            ),
        }
        for p in grupo.posiciones if p.cantidad > 0
    ]
    valor_cartera = sum(p["valor_mercado"] for p in posiciones)
    capital_total = grupo.capital_disponible + valor_cartera

    return {
        "grupo": grupo.nombre,
        "perfil_riesgo": grupo.perfil_riesgo,
        "capital_disponible": round(grupo.capital_disponible, 2),
        "valor_cartera": round(valor_cartera, 2),
        "capital_total": round(capital_total, 2),
        "rendimiento_pct": round((capital_total - capital_inicial) / capital_inicial * 100, 2),
        "posiciones": posiciones,
    }


# ── Operaciones ───────────────────────────────────────────────────────────────

class OperacionIn(BaseModel):
    instrumento_id: int
    tipo: str            # compra / venta
    cantidad: int
    confirmar_advertencia: bool = False   # el grupo confirmó a pesar de la advertencia


@router.post("/operar/preview")
def preview_operacion(
    body: OperacionIn,
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    """
    Calcula el impacto de la operación y verifica coherencia con el perfil.
    No ejecuta nada — solo retorna el análisis para que el frontend muestre la confirmación.
    """
    inst = db.query(Instrumento).filter(Instrumento.id == body.instrumento_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado")

    config = db.query(Configuracion).first()
    comision_pct = config.comision if config else 0.005
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    precio = inst.precio_actual
    monto_bruto = precio * body.cantidad
    comision = round(monto_bruto * comision_pct, 2)

    if body.tipo == "compra":
        monto_total = monto_bruto + comision
    else:
        monto_total = monto_bruto - comision

    # Verificar fondos / posición
    if body.tipo == "compra":
        if grupo.capital_disponible < monto_total:
            raise HTTPException(status_code=400, detail="Capital insuficiente")
    else:
        posicion = db.query(Posicion).filter(
            Posicion.grupo_id == grupo.id,
            Posicion.instrumento_id == body.instrumento_id
        ).first()
        if not posicion or posicion.cantidad < body.cantidad:
            raise HTTPException(status_code=400, detail="Cantidad insuficiente en cartera")

    # Valor total de la cartera para calcular exposición
    valor_cartera = sum(
        p.cantidad * p.instrumento.precio_actual
        for p in grupo.posiciones if p.cantidad > 0
    )
    capital_total = grupo.capital_disponible + valor_cartera

    # Verificar coherencia con perfil
    coherente, advertencia = True, ""
    if grupo.perfil_riesgo and body.tipo == "compra":
        coherente, advertencia = validar_coherencia(
            perfil=grupo.perfil_riesgo,
            volatilidad_instrumento=inst.volatilidad,
            monto_operacion=monto_total,
            capital_total=capital_total,
        )

    return {
        "instrumento": inst.ticker,
        "tipo": body.tipo,
        "cantidad": body.cantidad,
        "precio": precio,
        "monto_bruto": round(monto_bruto, 2),
        "comision": comision,
        "monto_total": round(monto_total, 2),
        "coherente_perfil": coherente,
        "advertencia": advertencia,
    }


@router.post("/operar")
def ejecutar_operacion(
    body: OperacionIn,
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    inst = db.query(Instrumento).filter(Instrumento.id == body.instrumento_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado")

    config = db.query(Configuracion).first()
    comision_pct = config.comision if config else 0.005
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    precio = inst.precio_actual
    monto_bruto = precio * body.cantidad
    comision = round(monto_bruto * comision_pct, 2)

    if body.tipo == "compra":
        monto_total = monto_bruto + comision
        if grupo.capital_disponible < monto_total:
            raise HTTPException(status_code=400, detail="Capital insuficiente")
    else:
        monto_total = monto_bruto - comision
        posicion = db.query(Posicion).filter(
            Posicion.grupo_id == grupo.id,
            Posicion.instrumento_id == body.instrumento_id
        ).first()
        if not posicion or posicion.cantidad < body.cantidad:
            raise HTTPException(status_code=400, detail="Cantidad insuficiente")

    # Verificar coherencia (para registrar advertencia)
    valor_cartera = sum(
        p.cantidad * p.instrumento.precio_actual
        for p in grupo.posiciones if p.cantidad > 0
    )
    capital_total = grupo.capital_disponible + valor_cartera
    advertencia_perfil = False
    if grupo.perfil_riesgo and body.tipo == "compra":
        coherente, _ = validar_coherencia(
            grupo.perfil_riesgo, inst.volatilidad, monto_total, capital_total
        )
        advertencia_perfil = not coherente

    # Noticia vigente más reciente
    ahora = datetime.utcnow()
    noticia_vigente = (
        db.query(Noticia)
        .filter(Noticia.publicado_en <= ahora, Noticia.activa == True)
        .order_by(Noticia.publicado_en.desc())
        .first()
    )

    # Ejecutar
    if body.tipo == "compra":
        grupo.capital_disponible -= monto_total
        posicion = db.query(Posicion).filter(
            Posicion.grupo_id == grupo.id,
            Posicion.instrumento_id == body.instrumento_id
        ).first()
        if posicion:
            # Actualizar precio promedio ponderado
            total_anterior = posicion.precio_promedio * posicion.cantidad
            posicion.precio_promedio = (total_anterior + monto_bruto) / (posicion.cantidad + body.cantidad)
            posicion.cantidad += body.cantidad
        else:
            db.add(Posicion(
                grupo_id=grupo.id,
                instrumento_id=body.instrumento_id,
                cantidad=body.cantidad,
                precio_promedio=precio,
            ))
    else:
        grupo.capital_disponible += monto_total
        posicion = db.query(Posicion).filter(
            Posicion.grupo_id == grupo.id,
            Posicion.instrumento_id == body.instrumento_id
        ).first()
        posicion.cantidad -= body.cantidad

    # Registrar operación
    op = Operacion(
        grupo_id=grupo.id,
        instrumento_id=body.instrumento_id,
        tipo=body.tipo,
        cantidad=body.cantidad,
        precio=precio,
        comision=comision,
        monto_total=round(monto_total, 2),
        noticia_id=noticia_vigente.id if noticia_vigente else None,
        advertencia_perfil=advertencia_perfil,
    )
    db.add(op)
    db.commit()

    return {
        "ok": True,
        "tipo": body.tipo,
        "instrumento": inst.ticker,
        "cantidad": body.cantidad,
        "precio": precio,
        "monto_total": round(monto_total, 2),
        "capital_disponible": round(grupo.capital_disponible, 2),
    }


@router.get("/operaciones")
def historial_operaciones(db: Session = Depends(get_db), grupo: Grupo = Depends(get_current_grupo)):
    ops = sorted(grupo.operaciones, key=lambda x: x.timestamp, reverse=True)
    return [
        {
            "id": o.id,
            "instrumento": o.instrumento.ticker,
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "comision": o.comision,
            "monto_total": o.monto_total,
            "advertencia_perfil": o.advertencia_perfil,
            "noticia": o.noticia.titulo if o.noticia else None,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in ops
    ]


# ── Noticias (vista del grupo) ────────────────────────────────────────────────

@router.get("/noticias")
def get_noticias(db: Session = Depends(get_db), grupo: Grupo = Depends(get_current_grupo)):
    ahora = datetime.utcnow()
    noticias = (
        db.query(Noticia)
        .filter(Noticia.publicado_en <= ahora, Noticia.activa == True)
        .order_by(Noticia.publicado_en.desc())
        .all()
    )
    leidas = {l.noticia_id for l in db.query(LecturaNoticia).filter(
        LecturaNoticia.grupo_id == grupo.id
    ).all()}
    return [
        {
            "id": n.id,
            "titulo": n.titulo,
            "contenido": n.contenido,
            "tipo": n.tipo,
            "ticker_relacionado": n.ticker_relacionado,
            "publicado_en": n.publicado_en.isoformat(),
            "leida": n.id in leidas,
        }
        for n in noticias
    ]


@router.post("/noticias/{noticia_id}/leer")
def marcar_leida(
    noticia_id: int,
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    ya = db.query(LecturaNoticia).filter(
        LecturaNoticia.noticia_id == noticia_id,
        LecturaNoticia.grupo_id == grupo.id
    ).first()
    if not ya:
        db.add(LecturaNoticia(noticia_id=noticia_id, grupo_id=grupo.id))
        db.commit()
    return {"ok": True}


# ── Cauciones ────────────────────────────────────────────────────────────────

PLAZOS_VALIDOS = {1, 7, 30, 60, 90}


class CaucionIn(BaseModel):
    monto: float
    plazo_dias: int   # 1 / 7 / 30 / 60 / 90


@router.post("/cauciones")
def constituir_caucion(
    body: CaucionIn,
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    if body.plazo_dias not in PLAZOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"Plazo inválido. Opciones: {sorted(PLAZOS_VALIDOS)}")
    if body.monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a 0")
    if body.monto > grupo.capital_disponible:
        raise HTTPException(status_code=400, detail="Capital insuficiente")

    config = db.query(Configuracion).first()
    tna = config.tasa_caucion if config else 0.60

    # Intereses = monto * TNA * (plazo / 365)
    intereses = round(body.monto * tna * body.plazo_dias / 365, 2)
    monto_total = round(body.monto + intereses, 2)

    ahora = datetime.utcnow()
    caucion = Caucion(
        grupo_id=grupo.id,
        monto=body.monto,
        tna=tna,
        plazo_dias=body.plazo_dias,
        intereses=intereses,
        monto_total=monto_total,
        constituida_en=ahora,
        vence_en=ahora + timedelta(days=body.plazo_dias),
    )
    grupo.capital_disponible -= body.monto
    db.add(caucion)
    db.commit()
    db.refresh(caucion)

    return {
        "id": caucion.id,
        "monto": caucion.monto,
        "tna_pct": round(tna * 100, 2),
        "plazo_dias": caucion.plazo_dias,
        "intereses": caucion.intereses,
        "monto_total": caucion.monto_total,
        "vence_en": caucion.vence_en.isoformat(),
        "capital_disponible": round(grupo.capital_disponible, 2),
    }


@router.get("/cauciones")
def listar_cauciones(
    db: Session = Depends(get_db),
    grupo: Grupo = Depends(get_current_grupo)
):
    cauciones = (
        db.query(Caucion)
        .filter(Caucion.grupo_id == grupo.id)
        .order_by(Caucion.constituida_en.desc())
        .all()
    )
    ahora = datetime.utcnow()
    return [
        {
            "id": c.id,
            "monto": c.monto,
            "tna_pct": round(c.tna * 100, 2),
            "plazo_dias": c.plazo_dias,
            "intereses": c.intereses,
            "monto_total": c.monto_total,
            "constituida_en": c.constituida_en.isoformat(),
            "vence_en": c.vence_en.isoformat(),
            "cobrada": c.cobrada,
            "dias_restantes": max(0, (c.vence_en - ahora).days),
        }
        for c in cauciones
    ]


# ── Ranking ───────────────────────────────────────────────────────────────────

@router.get("/ranking")
def get_ranking(db: Session = Depends(get_db), _=Depends(get_current_grupo)):
    config = db.query(Configuracion).first()
    capital_inicial = config.capital_inicial if config else 1_000_000.0
    grupos = db.query(Grupo).all()
    ranking = []
    for g in grupos:
        valor_cartera = sum(
            p.cantidad * p.instrumento.precio_actual
            for p in g.posiciones if p.cantidad > 0
        )
        capital_total = g.capital_disponible + valor_cartera
        rendimiento = (capital_total - capital_inicial) / capital_inicial * 100
        ranking.append({
            "grupo": g.nombre,
            "capital_total": round(capital_total, 2),
            "rendimiento_pct": round(rendimiento, 2),
        })
    ranking.sort(key=lambda x: x["rendimiento_pct"], reverse=True)
    for i, r in enumerate(ranking, 1):
        r["posicion"] = i
    return ranking
