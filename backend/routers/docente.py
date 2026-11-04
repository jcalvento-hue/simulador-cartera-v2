"""Router del docente — gestión de alumnos, grupos, noticias, reportes"""
import csv, io, secrets, string
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import (
    Alumno, Grupo, Noticia, LecturaNoticia, Operacion,
    Instrumento, Configuracion, get_db, Docente, PerfilGrupo
)
from auth import get_current_docente
from market import generar_historial_inicial

router = APIRouter(prefix="/api/docente", tags=["docente"])


def _codigo_grupo() -> str:
    """Genera un código de acceso de 6 caracteres alfanumérico."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(6))


# ── Alumnos ───────────────────────────────────────────────────────────────────

class AlumnoIn(BaseModel):
    nombre: str
    apellido: str
    legajo: Optional[str] = None
    email: Optional[str] = None


@router.get("/alumnos")
def listar_alumnos(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    alumnos = db.query(Alumno).all()
    return [
        {
            "id": a.id, "nombre": a.nombre, "apellido": a.apellido,
            "legajo": a.legajo, "email": a.email,
            "grupo_id": a.grupo_id,
            "grupo_nombre": a.grupo.nombre if a.grupo else None
        }
        for a in alumnos
    ]


@router.post("/alumnos")
def crear_alumno(body: AlumnoIn, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    alumno = Alumno(**body.dict())
    db.add(alumno)
    db.commit()
    db.refresh(alumno)
    return {"id": alumno.id, "nombre": alumno.nombre, "apellido": alumno.apellido}


@router.post("/alumnos/csv")
async def cargar_alumnos_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """
    CSV esperado: nombre,apellido,legajo,email
    Primera fila = encabezado (se ignora si contiene 'nombre')
    """
    content = await file.read()
    text = content.decode("utf-8-sig")
    # Auto-detecta separador (coma o punto y coma)
    sample = text[:1024]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)

    # Normaliza encabezados a minúscula para aceptar Nombre, NOMBRE, nombre, etc.
    def col(row, *keys):
        row_lower = {k.strip().lower(): v for k, v in row.items()}
        for k in keys:
            if k in row_lower:
                return row_lower[k].strip()
        return ""

    creados, errores = 0, []
    for i, row in enumerate(reader, 1):
        try:
            nombre = col(row, "nombre", "name")
            apellido = col(row, "apellido", "lastname", "surname")
            if not nombre or not apellido:
                errores.append(f"Fila {i}: nombre o apellido vacío")
                continue
            legajo_raw = col(row, "legajo", "id", "dni")
            legajo = legajo_raw if legajo_raw and legajo_raw.lower() not in ("sin definir", "s/d", "nd", "n/a", "-", "") else None
            email = col(row, "email", "mail", "correo") or None

            # Si ya existe el legajo, actualiza
            if legajo:
                existente = db.query(Alumno).filter(Alumno.legajo == legajo).first()
                if existente:
                    existente.nombre = nombre
                    existente.apellido = apellido
                    existente.email = email
                    creados += 1
                    continue

            db.add(Alumno(nombre=nombre, apellido=apellido, legajo=legajo, email=email))
            creados += 1
        except Exception as e:
            errores.append(f"Fila {i}: {e}")

    db.commit()
    return {"creados": creados, "errores": errores}


# ── Grupos ────────────────────────────────────────────────────────────────────

class GrupoIn(BaseModel):
    nombre: str


class AsignarAlumnosIn(BaseModel):
    alumno_ids: List[int]


@router.get("/grupos")
def listar_grupos(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    grupos = db.query(Grupo).all()
    result = []
    for g in grupos:
        # Valor de mercado de la cartera
        valor_cartera = sum(
            p.cantidad * p.instrumento.precio_actual
            for p in g.posiciones if p.cantidad > 0
        )
        capital_total = g.capital_disponible + valor_cartera
        result.append({
            "id": g.id,
            "nombre": g.nombre,
            "codigo_acceso": g.codigo_acceso,
            "capital_disponible": g.capital_disponible,
            "valor_cartera": valor_cartera,
            "capital_total": capital_total,
            "perfil_riesgo": g.perfil_riesgo,
            "encuesta_completada": g.encuesta_completada,
            "alumnos": [{"id": a.id, "nombre": a.nombre, "apellido": a.apellido} for a in g.alumnos],
            "num_operaciones": len(g.operaciones),
        })
    return result


@router.post("/grupos")
def crear_grupo(body: GrupoIn, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    if db.query(Grupo).filter(Grupo.nombre == body.nombre).first():
        raise HTTPException(status_code=400, detail="Ya existe un grupo con ese nombre")
    config = db.query(Configuracion).first()
    capital = config.capital_inicial if config else 1_000_000.0
    grupo = Grupo(
        nombre=body.nombre,
        codigo_acceso=_codigo_grupo(),
        capital_disponible=capital
    )
    db.add(grupo)
    db.commit()
    db.refresh(grupo)
    return {"id": grupo.id, "nombre": grupo.nombre, "codigo_acceso": grupo.codigo_acceso}


@router.post("/grupos/{grupo_id}/alumnos")
def asignar_alumnos(
    grupo_id: int,
    body: AsignarAlumnosIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    for aid in body.alumno_ids:
        alumno = db.query(Alumno).filter(Alumno.id == aid).first()
        if alumno:
            alumno.grupo_id = grupo_id
    db.commit()
    return {"ok": True}


# ── Noticias ──────────────────────────────────────────────────────────────────

class NoticiaIn(BaseModel):
    titulo: str
    contenido: str
    tipo: str = "fundamental"           # fundamental / tecnico
    ticker_relacionado: Optional[str] = None
    publicado_en: datetime              # ISO string desde el frontend


@router.get("/noticias")
def listar_noticias(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    noticias = db.query(Noticia).order_by(Noticia.publicado_en).all()
    return [
        {
            "id": n.id, "titulo": n.titulo, "tipo": n.tipo,
            "ticker_relacionado": n.ticker_relacionado,
            "publicado_en": n.publicado_en.isoformat(),
            "activa": n.activa,
            "lecturas": len(n.lecturas),
        }
        for n in noticias
    ]


@router.post("/noticias")
def crear_noticia(body: NoticiaIn, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    noticia = Noticia(**body.dict())
    db.add(noticia)
    db.commit()
    db.refresh(noticia)
    return {"id": noticia.id, "titulo": noticia.titulo}


@router.delete("/noticias/{noticia_id}")
def eliminar_noticia(noticia_id: int, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    noticia = db.query(Noticia).filter(Noticia.id == noticia_id).first()
    if not noticia:
        raise HTTPException(status_code=404, detail="Noticia no encontrada")
    # Eliminar lecturas asociadas antes de borrar la noticia
    db.query(LecturaNoticia).filter(LecturaNoticia.noticia_id == noticia_id).delete()
    db.delete(noticia)
    db.commit()
    return {"ok": True}


@router.post("/noticias/reset")
def reset_noticias(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Elimina TODAS las noticias y sus lecturas."""
    db.query(LecturaNoticia).delete()
    db.query(Noticia).delete()
    db.commit()
    return {"ok": True, "mensaje": "Todas las noticias eliminadas"}


# ── DELETE / RESET grupos y alumnos ──────────────────────────────────────────

from models import Caucion, Posicion, RespuestaEncuesta

@router.delete("/alumnos/{alumno_id}")
def eliminar_alumno(alumno_id: int, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    alumno = db.query(Alumno).filter(Alumno.id == alumno_id).first()
    if not alumno:
        raise HTTPException(status_code=404, detail="Alumno no encontrado")
    db.delete(alumno)
    db.commit()
    return {"ok": True}


@router.post("/alumnos/reset")
def reset_alumnos(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Desvincula y elimina TODOS los alumnos."""
    db.query(Alumno).delete()
    db.commit()
    return {"ok": True, "mensaje": "Todos los alumnos eliminados"}


@router.delete("/grupos/{grupo_id}")
def eliminar_grupo(grupo_id: int, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Elimina un grupo y todas sus operaciones, posiciones, cauciones y perfil."""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    # Desvincular alumnos
    db.query(Alumno).filter(Alumno.grupo_id == grupo_id).update({"grupo_id": None})
    # Eliminar datos asociados
    db.query(PerfilGrupo).filter(PerfilGrupo.grupo_id == grupo_id).delete()
    db.query(LecturaNoticia).filter(LecturaNoticia.grupo_id == grupo_id).delete()
    db.query(Caucion).filter(Caucion.grupo_id == grupo_id).delete()
    db.query(Posicion).filter(Posicion.grupo_id == grupo_id).delete()
    db.query(Operacion).filter(Operacion.grupo_id == grupo_id).delete()
    db.query(RespuestaEncuesta).filter(RespuestaEncuesta.grupo_id == grupo_id).delete()
    db.delete(grupo)
    db.commit()
    return {"ok": True}


@router.post("/grupos/reset")
def reset_grupos(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Elimina TODOS los grupos, sus operaciones, posiciones, cauciones y perfiles.
    Los alumnos quedan desvinculados pero no se eliminan."""
    # Desvincular alumnos
    db.query(Alumno).update({"grupo_id": None})
    # Eliminar todo lo relacionado
    db.query(PerfilGrupo).delete()
    db.query(LecturaNoticia).delete()
    db.query(Caucion).delete()
    db.query(Posicion).delete()
    db.query(Operacion).delete()
    db.query(RespuestaEncuesta).delete()
    db.query(Grupo).delete()
    db.commit()
    return {"ok": True, "mensaje": "Todos los grupos eliminados"}


# ── Reportes ──────────────────────────────────────────────────────────────────

@router.get("/reportes/operaciones")
def reporte_operaciones(
    grupo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """Historial completo de operaciones, opcionalmente filtrado por grupo."""
    q = db.query(Operacion)
    if grupo_id:
        q = q.filter(Operacion.grupo_id == grupo_id)
    ops = q.order_by(Operacion.timestamp).all()
    return [
        {
            "id": o.id,
            "grupo": o.grupo.nombre,
            "instrumento": o.instrumento.ticker,
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "comision": o.comision,
            "monto_total": o.monto_total,
            "advertencia_perfil": o.advertencia_perfil,
            "noticia": {"id": o.noticia.id, "titulo": o.noticia.titulo} if o.noticia else None,
            "justificacion": o.justificacion,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in ops
    ]


@router.get("/reportes/noticias/{noticia_id}")
def reporte_noticia(
    noticia_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """Para una noticia: qué grupos la leyeron y qué operaron después."""
    noticia = db.query(Noticia).filter(Noticia.id == noticia_id).first()
    if not noticia:
        raise HTTPException(status_code=404, detail="Noticia no encontrada")

    lecturas = db.query(LecturaNoticia).filter(LecturaNoticia.noticia_id == noticia_id).all()
    grupos_que_leyeron = {l.grupo_id: l.leida_en for l in lecturas}

    # Operaciones realizadas DESPUÉS de la lectura (en ese instrumento si está relacionado)
    operaciones_post = []
    for op in db.query(Operacion).filter(Operacion.noticia_id == noticia_id).all():
        operaciones_post.append({
            "grupo": op.grupo.nombre,
            "instrumento": op.instrumento.ticker,
            "tipo": op.tipo,
            "cantidad": op.cantidad,
            "precio": op.precio,
            "timestamp": op.timestamp.isoformat(),
        })

    return {
        "noticia": {
            "id": noticia.id,
            "titulo": noticia.titulo,
            "tipo": noticia.tipo,
            "ticker_relacionado": noticia.ticker_relacionado,
            "publicado_en": noticia.publicado_en.isoformat(),
        },
        "grupos_que_leyeron": len(grupos_que_leyeron),
        "operaciones_post_noticia": operaciones_post,
    }


@router.get("/reportes/bitacoras")
def reporte_bitacoras(
    grupo_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """Bitácora de decisiones: todas las justificaciones de operaciones, ordenadas por grupo y fecha."""
    q = db.query(Operacion).filter(Operacion.justificacion != None)
    if grupo_id:
        q = q.filter(Operacion.grupo_id == grupo_id)
    ops = q.order_by(Operacion.grupo_id, Operacion.timestamp).all()
    return [
        {
            "id": o.id,
            "grupo": o.grupo.nombre,
            "instrumento": o.instrumento.ticker,
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "monto_total": o.monto_total,
            "justificacion": o.justificacion,
            "advertencia_perfil": o.advertencia_perfil,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in ops
    ]


@router.get("/reportes/ranking")
def reporte_ranking(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Ranking de grupos por rendimiento."""
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
            "num_operaciones": len(g.operaciones),
            "perfil_riesgo": g.perfil_riesgo,
        })

    ranking.sort(key=lambda x: x["rendimiento_pct"], reverse=True)
    for i, r in enumerate(ranking, 1):
        r["posicion"] = i
    return ranking


@router.get("/reportes/grupo/{grupo_id}")
def reporte_grupo(
    grupo_id: int,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """Reporte completo de un grupo: perfil, cartera, operaciones, noticias leídas."""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    config = db.query(Configuracion).first()
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    posiciones = [
        {
            "ticker": p.instrumento.ticker,
            "nombre": p.instrumento.nombre,
            "cantidad": p.cantidad,
            "precio_actual": p.instrumento.precio_actual,
            "precio_promedio": p.precio_promedio,
            "valor_mercado": p.cantidad * p.instrumento.precio_actual,
            "resultado": (p.instrumento.precio_actual - p.precio_promedio) * p.cantidad,
        }
        for p in grupo.posiciones if p.cantidad > 0
    ]
    valor_cartera = sum(p["valor_mercado"] for p in posiciones)
    capital_total = grupo.capital_disponible + valor_cartera

    operaciones = [
        {
            "instrumento": o.instrumento.ticker,
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "monto_total": o.monto_total,
            "advertencia_perfil": o.advertencia_perfil,
            "noticia": o.noticia.titulo if o.noticia else None,
            "justificacion": o.justificacion,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in sorted(grupo.operaciones, key=lambda x: x.timestamp)
    ]

    noticias_leidas = [
        {
            "noticia": l.noticia.titulo,
            "tipo": l.noticia.tipo,
            "leida_en": l.leida_en.isoformat(),
        }
        for l in grupo.lecturas
    ] if hasattr(grupo, 'lecturas') else []

    return {
        "grupo": grupo.nombre,
        "alumnos": [f"{a.nombre} {a.apellido}" for a in grupo.alumnos],
        "perfil_riesgo": grupo.perfil_riesgo,
        "capital_inicial": capital_inicial,
        "capital_disponible": grupo.capital_disponible,
        "valor_cartera": valor_cartera,
        "capital_total": capital_total,
        "rendimiento_pct": round((capital_total - capital_inicial) / capital_inicial * 100, 2),
        "posiciones": posiciones,
        "operaciones": operaciones,
        "noticias_leidas": noticias_leidas,
    }


# ── Instrumentos (sector + tendencia) ────────────────────────────────────────

@router.get("/instrumentos")
def listar_instrumentos(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    instrumentos = db.query(Instrumento).filter(Instrumento.activo == True).order_by(Instrumento.tipo, Instrumento.ticker).all()
    return [
        {
            "id": i.id,
            "ticker": i.ticker,
            "nombre": i.nombre,
            "tipo": i.tipo,
            "sector": i.sector,
            "tendencia_esperada": i.tendencia_esperada,
            "precio_actual": i.precio_actual,
            "volatilidad": i.volatilidad,
        }
        for i in instrumentos
    ]


class InstrumentoUpdateIn(BaseModel):
    sector: Optional[str] = None
    tendencia_esperada: Optional[float] = None  # % total al vencimiento, ej: 0.15 = +15%, -0.08 = -8%


@router.put("/instrumentos/{instrumento_id}")
def update_instrumento(
    instrumento_id: int,
    body: InstrumentoUpdateIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    inst = db.query(Instrumento).filter(Instrumento.id == instrumento_id).first()
    if not inst:
        raise HTTPException(status_code=404, detail="Instrumento no encontrado")
    if body.sector is not None:
        inst.sector = body.sector
    if body.tendencia_esperada is not None:
        inst.tendencia_esperada = body.tendencia_esperada
    db.commit()
    return {"ok": True, "ticker": inst.ticker, "sector": inst.sector, "tendencia_esperada": inst.tendencia_esperada}


# ── Perfil de grupo (asignado por docente) ───────────────────────────────────

class PerfilGrupoIn(BaseModel):
    estilo: Optional[str] = "moderado"           # conservador / moderado / agresivo / libre
    max_pct_por_activo: Optional[float] = None
    max_pct_por_sector: Optional[float] = None
    min_activos: Optional[int] = None
    min_sectores: Optional[int] = None
    min_pct_renta_fija: Optional[float] = None
    max_pct_renta_fija: Optional[float] = None
    min_pct_renta_variable: Optional[float] = None
    max_pct_renta_variable: Optional[float] = None
    min_pct_liquidez: Optional[float] = None
    max_pct_liquidez: Optional[float] = None
    respetar_tendencia: Optional[bool] = False
    notas: Optional[str] = None


@router.get("/grupos/{grupo_id}/perfil")
def get_perfil_grupo(grupo_id: int, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    p = db.query(PerfilGrupo).filter(PerfilGrupo.grupo_id == grupo_id).first()
    if not p:
        return {"asignado": False}
    return {
        "asignado": True,
        "estilo": p.estilo,
        "max_pct_por_activo": p.max_pct_por_activo,
        "max_pct_por_sector": p.max_pct_por_sector,
        "min_activos": p.min_activos,
        "min_sectores": p.min_sectores,
        "min_pct_renta_fija": p.min_pct_renta_fija,
        "max_pct_renta_fija": p.max_pct_renta_fija,
        "min_pct_renta_variable": p.min_pct_renta_variable,
        "max_pct_renta_variable": p.max_pct_renta_variable,
        "min_pct_liquidez": p.min_pct_liquidez,
        "max_pct_liquidez": p.max_pct_liquidez,
        "respetar_tendencia": p.respetar_tendencia,
        "notas": p.notas,
    }


@router.put("/grupos/{grupo_id}/perfil")
def asignar_perfil_grupo(
    grupo_id: int,
    body: PerfilGrupoIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")

    p = db.query(PerfilGrupo).filter(PerfilGrupo.grupo_id == grupo_id).first()
    if not p:
        p = PerfilGrupo(grupo_id=grupo_id)
        db.add(p)

    for field, val in body.dict().items():
        setattr(p, field, val)

    # Sincronizar estilo en Grupo.perfil_riesgo para mantener compatibilidad
    grupo.perfil_riesgo = body.estilo
    grupo.encuesta_completada = True   # marca como si hubiera completado el perfil

    db.commit()
    return {"ok": True, "grupo": grupo.nombre, "estilo": p.estilo}


@router.post("/configuracion/regenerar-historial")
def regenerar_historial(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Regenera el historial de precios para todos los instrumentos activos (últimas 2 horas)."""
    generar_historial_inicial(db=db, horas=2.0)
    return {"ok": True, "mensaje": "Historial regenerado correctamente."}


@router.get("/configuracion")
def get_config(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    config = db.query(Configuracion).first()
    return {
        "nombre_experiencia": config.nombre_experiencia,
        "capital_inicial": config.capital_inicial,
        "comision": config.comision,
        "activo": config.activo,
        "fecha_inicio": config.fecha_inicio.isoformat() if config.fecha_inicio else None,
        "fecha_fin": config.fecha_fin.isoformat() if config.fecha_fin else None,
    }


class ConfigIn(BaseModel):
    nombre_experiencia: Optional[str] = None
    capital_inicial: Optional[float] = None
    comision: Optional[float] = None
    activo: Optional[bool] = None
    fecha_inicio: Optional[str] = None   # ISO 8601, ej: "2024-11-01T08:00"
    fecha_fin: Optional[str] = None      # ISO 8601, ej: "2024-12-15T23:59"


@router.put("/configuracion")
def update_config(body: ConfigIn, db: Session = Depends(get_db), _=Depends(get_current_docente)):
    config = db.query(Configuracion).first()
    if not config:
        config = Configuracion()
        db.add(config)

    estaba_inactivo = not config.activo
    from datetime import datetime as _dt
    data = body.dict(exclude_none=True)
    # Parsear fechas ISO 8601 a datetime antes de guardar
    for fecha_field in ("fecha_inicio", "fecha_fin"):
        if fecha_field in data:
            try:
                data[fecha_field] = _dt.fromisoformat(data[fecha_field])
            except (ValueError, TypeError):
                data.pop(fecha_field)
    for field, val in data.items():
        setattr(config, field, val)
    db.commit()

    # Si el simulador acaba de activarse, generar historial retroactivo (2 horas)
    if body.activo is True and estaba_inactivo:
        generar_historial_inicial(db=db, horas=2.0)

    return {"ok": True}
