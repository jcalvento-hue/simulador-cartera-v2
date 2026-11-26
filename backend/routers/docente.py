"""Router del docente — gestión de alumnos, grupos, noticias, reportes"""
import csv, io, secrets, string, os
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
    Instrumento, Configuracion, get_db, Docente, PerfilGrupo, HistorialCapital
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
    sector_relacionado: Optional[str] = None  # sector afectado (alternativa al ticker)
    publicado_en: datetime              # ISO string desde el frontend
    duracion_horas: Optional[float] = None    # None = sin vencimiento
    impacto_pct: Optional[float] = None       # % de impacto total, ej: 5.0 = 5%
    impacto_tipo: Optional[str] = None        # "suba" | "baja"


@router.get("/noticias")
def listar_noticias(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    from datetime import timedelta
    ahora = datetime.utcnow()
    noticias = db.query(Noticia).order_by(Noticia.publicado_en).all()
    return [
        {
            "id": n.id, "titulo": n.titulo, "tipo": n.tipo,
            "ticker_relacionado": n.ticker_relacionado,
            "publicado_en": n.publicado_en.isoformat(),
            "duracion_horas": n.duracion_horas,
            "expira_en": (n.publicado_en + timedelta(hours=n.duracion_horas)).isoformat() if n.duracion_horas else None,
            "impacto_pct": n.impacto_pct,
            "impacto_tipo": n.impacto_tipo,
            "sector_relacionado": getattr(n, "sector_relacionado", None),
            "activa": n.activa,
            "vigente": n.activa and n.publicado_en <= ahora and (
                n.duracion_horas is None or
                n.publicado_en + timedelta(hours=n.duracion_horas) >= ahora
            ),
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
            "snapshot_indicadores": o.snapshot_indicadores,
            "noticias_activas": o.noticias_activas,
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
    """Bitácora de decisiones: todas las justificaciones de operaciones, ordenadas por grupo y fecha.
    Incluye snapshot de indicadores técnicos y noticias activas al momento de cada operación."""
    q = db.query(Operacion)
    if grupo_id:
        q = q.filter(Operacion.grupo_id == grupo_id)
    ops = q.order_by(Operacion.grupo_id, Operacion.timestamp).all()
    return [
        {
            "id": o.id,
            "grupo": o.grupo.nombre,
            "instrumento": o.instrumento.ticker,
            "nombre_instrumento": o.instrumento.nombre,
            "tipo": o.tipo,
            "cantidad": o.cantidad,
            "precio": o.precio,
            "monto_total": o.monto_total,
            "justificacion": o.justificacion,
            "advertencia_perfil": o.advertencia_perfil,
            "snapshot_indicadores": o.snapshot_indicadores,
            "noticias_activas": o.noticias_activas,
            "timestamp": o.timestamp.isoformat(),
        }
        for o in ops
    ]


@router.get("/reportes/metricas")
def reporte_metricas(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """Métricas de riesgo de todos los grupos: Sharpe, drawdown, volatilidad."""
    import math
    config = db.query(Configuracion).first()
    capital_inicial = config.capital_inicial if config else 1_000_000.0

    grupos = db.query(Grupo).all()
    resultado = []
    for g in grupos:
        snapshots = (
            db.query(HistorialCapital)
            .filter(HistorialCapital.grupo_id == g.id)
            .order_by(HistorialCapital.timestamp)
            .all()
        )
        if len(snapshots) < 2:
            resultado.append({
                "grupo": g.nombre,
                "sharpe": None,
                "max_drawdown_pct": None,
                "volatilidad_pct": None,
                "rendimiento_pct": None,
                "n_snapshots": len(snapshots),
            })
            continue

        valores = [s.capital_total for s in snapshots]
        retornos = [(valores[i] - valores[i-1]) / valores[i-1] for i in range(1, len(valores))]
        n = len(retornos)
        media = sum(retornos) / n
        varianza = sum((r - media) ** 2 for r in retornos) / n
        std = math.sqrt(varianza) if varianza > 0 else 0
        sharpe = round(media / std, 3) if std > 0 else None
        vol_anual = round(std * math.sqrt(252) * 100, 2) if std > 0 else 0.0

        max_dd = 0.0
        pico = valores[0]
        for v in valores[1:]:
            if v > pico:
                pico = v
            dd = (pico - v) / pico if pico > 0 else 0
            if dd > max_dd:
                max_dd = dd

        resultado.append({
            "grupo": g.nombre,
            "sharpe": sharpe,
            "max_drawdown_pct": round(max_dd * 100, 2),
            "volatilidad_pct": vol_anual,
            "rendimiento_pct": round((valores[-1] - capital_inicial) / capital_inicial * 100, 2),
            "n_snapshots": len(snapshots),
        })
    return resultado


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


class SetPreciosIn(BaseModel):
    precios: dict  # {ticker: precio_float}


@router.post("/configuracion/set-precios")
def set_precios_semilla(
    body: SetPreciosIn,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """
    Recibe precios reales descargados desde el browser (CORS libre) y los guarda
    como precio_inicial / precio_actual antes de regenerar el historial.
    El frontend descarga los precios y los envía aquí; luego llama a regenerar-historial.
    """
    actualizados = 0
    for ticker, precio in body.precios.items():
        try:
            precio_f = float(precio)
            if precio_f <= 0:
                continue
            inst = db.query(Instrumento).filter(Instrumento.ticker == ticker).first()
            if inst:
                inst.precio_inicial = precio_f
                inst.precio_actual  = precio_f
                inst.precio_sesion  = precio_f
                actualizados += 1
                print(f"[set-precios] {ticker} → {precio_f}", flush=True)
        except (ValueError, TypeError):
            continue
    db.commit()
    print(f"[set-precios] {actualizados} instrumentos actualizados.", flush=True)
    return {"ok": True, "actualizados": actualizados}


@router.post("/configuracion/regenerar-historial")
def regenerar_historial(db: Session = Depends(get_db), _=Depends(get_current_docente)):
    """
    Regenera el historial de precios para todos los instrumentos activos (últimas 2 horas).
    1. Descarga precios actuales: Rava (acciones AR) + Finnhub (acciones US).
    2. Actualiza precio_actual / precio_inicial en la DB con los precios reales.
    3. Genera el GBM retroactivo desde esos precios.
    Los instrumentos sin precio (bonos, FCIs) conservan su precio actual.
    """
    from historial_real import obtener_precios_actuales

    print("[regenerar] Descargando precios actuales (Rava + Finnhub)...", flush=True)
    precios = obtener_precios_actuales()

    actualizados = 0
    for ticker, precio in precios.items():
        try:
            inst = db.query(Instrumento).filter(Instrumento.ticker == ticker).first()
            if inst and precio > 0:
                inst.precio_inicial = precio
                inst.precio_actual  = precio
                inst.precio_sesion  = precio
                actualizados += 1
        except Exception as e:
            print(f"[regenerar] Error actualizando {ticker}: {e}", flush=True)
    db.commit()
    print(f"[regenerar] {actualizados} instrumentos actualizados con precios reales.", flush=True)

    print("[regenerar] Generando historial GBM...", flush=True)
    generar_historial_inicial(db=db, horas=2.0)
    print("[regenerar] Regeneración completada.", flush=True)
    return {"ok": True, "mensaje": f"Historial regenerado. {actualizados} precios actualizados desde Rava/Finnhub."}


@router.get("/configuracion/test-historial")
def test_historial_real(_=Depends(get_current_docente)):
    """Endpoint de diagnóstico: testea descarga de historial real para GGAL."""
    from historial_real import obtener_historial_real
    import traceback
    try:
        datos = obtener_historial_real("GGAL")
        if datos:
            return {
                "ok": True,
                "ticker": "GGAL",
                "puntos": len(datos),
                "primero": datos[0],
                "ultimo": datos[-1],
            }
        else:
            return {"ok": False, "error": "obtener_historial_real devolvió lista vacía"}
    except Exception as e:
        return {"ok": False, "error": str(e), "traceback": traceback.format_exc()}


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


# ── Generador de noticias con IA ─────────────────────────────────────────────

class GenerarNoticiaBody(BaseModel):
    ticker: Optional[str] = None
    sector: Optional[str] = None
    nombre_instrumento: Optional[str] = None
    precio_actual: float
    precio_objetivo: float
    duracion_horas: Optional[float] = 2.0


@router.post("/noticias/generar-ia")
def generar_noticia_ia(
    body: GenerarNoticiaBody,
    db: Session = Depends(get_db),
    _=Depends(get_current_docente)
):
    """
    Genera título y contenido de una noticia de mercado usando plantillas inteligentes
    coherentes con el movimiento de precio implícito (precio_actual → precio_objetivo).
    Calcula automáticamente impacto_pct e impacto_tipo. Sin dependencia de API externa.
    """
    import random

    # Calcular impacto
    delta_pct = round((body.precio_objetivo / body.precio_actual - 1) * 100, 2)
    impacto_tipo = "suba" if delta_pct > 0 else "baja"
    impacto_pct = abs(round(delta_pct, 2))

    nombre = body.nombre_instrumento or body.ticker or body.sector or "el activo"
    ticker = body.ticker or ""
    sector = body.sector or ""
    sube = delta_pct > 0
    magnitud = "leve" if impacto_pct < 3 else ("moderada" if impacto_pct < 8 else "significativa")
    durh = body.duracion_horas or 2.0

    # Detectar tipo de instrumento por ticker
    es_bono = ticker in ("AL30","GD30","AL35","AE38","TX26","T2X5")
    es_cedear = ticker in ("AAPL","GOOGL","AMZN","MSFT","TSLA","BRKB")
    es_fci = ticker.startswith("FCI")
    es_accion = not es_bono and not es_cedear and not es_fci

    # ── Plantillas prospectivas (se publican ANTES del movimiento) ───────────
    # Todas en tiempo futuro/condicional: "se espera", "podría", "analistas anticipan"
    if es_bono:
        titulos_suba = [
            f"Señales del FMI podrían impulsar a {nombre} en las próximas horas",
            f"{ticker}: acuerdo fiscal esperado presionaría la TIR a la baja",
            f"Datos de reservas del BCRA abren margen para rally en bonos soberanos",
            f"Inversores anticipan compresión de spread en {nombre}",
        ]
        titulos_baja = [
            f"Incertidumbre cambiaria podría golpear a {nombre} en la próxima rueda",
            f"{ticker}: vencimiento de deuda sin financiamiento confirmado genera cautela",
            f"Salida de capitales de emergentes amenaza a bonos soberanos como {ticker}",
            f"Toma de ganancias esperada en {nombre} tras semanas de rally",
        ]
        contenidos_suba = [
            f"Fuentes del mercado anticipan una jornada positiva para los títulos públicos en dólares. El contexto para {nombre} ({ticker}) mejora tras señales favorables del Fondo Monetario Internacional respecto al cumplimiento de metas fiscales, lo que reduciría la prima de riesgo país en las próximas horas.\n\nAnálisis de research local proyectan que la compresión de TIR podría acercar la paridad del {ticker} a niveles de sus comparables regionales. Los operadores estarían posicionándose en anticipación a un dato de reservas mejor al esperado.\n\nSe estima que el efecto podría materializarse durante las próximas {durh:.0f} horas. El volumen de operaciones en BYMA será clave para confirmar si hay convicción real detrás del movimiento.",
            f"El mercado de renta fija soberana muestra señales de mayor apetito por riesgo argentino. Analistas anticipan que {nombre} ({ticker}) podría beneficiarse de una mejora en el flujo de capitales hacia emergentes, impulsado por expectativas de baja de tasas en EE.UU.\n\nFondos internacionales habrían iniciado posiciones en la curva soberana argentina, lo que presionaría al alza las paridades. La relación TIR/duration del {ticker} luce atractiva para inversores con horizonte de mediano plazo.\n\nEl catalizador podría activarse en las próximas {durh:.0f} horas, aunque analistas advierten que el impacto dependerá de que no haya novedades adversas en el frente cambiario.",
        ]
        contenidos_baja = [
            f"El mercado de bonos soberanos enfrenta presiones que podrían traducirse en caídas de precio para {nombre} ({ticker}) en las próximas horas. La incertidumbre en torno al financiamiento de vencimientos de corto plazo generó una salida de posiciones por parte de inversores institucionales.\n\nFondos de cobertura habrían incrementado su exposición vendedora en la curva soberana argentina, anticipando una ampliación del spread. El BCRA no descartaría intervenciones que compliquen el flujo hacia instrumentos en dólares.\n\nAnálisis técnico sugiere que, de no revertirse las condiciones, la presión podría extenderse durante las próximas {durh:.0f} horas. Se recomienda precaución antes de incrementar posición en este tramo de la curva.",
            f"Señales de cautela se acumulan en torno a los títulos soberanos. {nombre} ({ticker}) podría verse afectado por una salida de capitales de mercados emergentes, en un contexto donde inversores globales reducen exposición a activos de riesgo ante datos de inflación adversos en EE.UU.\n\nEl riesgo país podría escalar si el Gobierno no confirma en las próximas horas el acceso a financiamiento para los vencimientos del trimestre. Operadores locales ya habrían comenzado a reducir duration en sus carteras.\n\nEl impacto estimado podría materializarse en las próximas {durh:.0f} horas. Analistas sugieren aguardar definiciones de política monetaria antes de tomar nuevas posiciones.",
        ]
        titulos = titulos_suba if sube else titulos_baja
        contenidos = contenidos_suba if sube else contenidos_baja

    elif es_cedear:
        empresa_map = {"AAPL": "Apple", "GOOGL": "Alphabet/Google", "AMZN": "Amazon", "MSFT": "Microsoft", "TSLA": "Tesla", "BRKB": "Berkshire Hathaway"}
        empresa = empresa_map.get(ticker, nombre)
        titulos_suba = [
            f"{empresa} publica resultados: analistas esperan sorpresa positiva que impulse {ticker}",
            f"Wall Street podría arrastrar al alza a los CEDEARs de {empresa}",
            f"Guidance de {empresa} generaría optimismo: mercado anticipa movimiento en {ticker}",
            f"Revisión al alza de estimaciones beneficiaría a tenedores de {ticker}",
        ]
        titulos_baja = [
            f"Datos macro de EE.UU. podrían presionar a los CEDEARs de {empresa}",
            f"{empresa} enfrenta revisión de estimaciones: {ticker} en zona de riesgo",
            f"Rotación hacia defensivos amenaza a {ticker} en las próximas ruedas",
            f"Dólar fuerte y tasas altas generan perspectiva negativa para {empresa}",
        ]
        contenidos_suba = [
            f"El mercado anticipa con optimismo la presentación de resultados trimestrales de {empresa}. Analistas del sell-side proyectan que las cifras podrían superar el consenso, lo que impulsaría al alza los CEDEARs de {ticker} en el mercado local durante las próximas {durh:.0f} horas.\n\nFondos de inversión con exposición a tecnología estadounidense habrían incrementado posiciones anticipando el dato. La relación precio/ganancia proyectada luce atractiva si los márgenes operativos cumplen las expectativas del management.\n\nEl efecto cambiario amplificaría el movimiento en pesos: una suba en dólares en Wall Street se potencia por la brecha entre el dólar CCL y el tipo de cambio oficial. Inversores deberán monitorear el volumen de operaciones de {ticker} en BYMA como señal de convicción.",
            f"Señales técnicas y fundamentales se alinean para {empresa} ({ticker}). El consenso de analistas apunta a una revisión al alza de los precios objetivo tras el guidance que la compañía daría a conocer en las próximas horas, lo que podría desencadenar compras en los CEDEARs.\n\nLa expectativa de un ciclo de baja de tasas de la Fed favorece a las empresas de alto crecimiento, que ven reducido su costo de capital. {empresa} estaría entre las más beneficiadas del sector dado su perfil de flujos de caja proyectados.\n\nEl movimiento podría materializarse en las próximas {durh:.0f} horas, aunque inversores deben considerar la volatilidad adicional por el factor tipo de cambio implícito en los CEDEARs.",
        ]
        contenidos_baja = [
            f"El entorno macro en EE.UU. genera perspectivas negativas para {empresa} ({ticker}). Datos de inflación por encima de lo esperado reducirían las probabilidades de un recorte de tasas de la Fed, lo que presiona la valuación de compañías de alto múltiplo como {empresa}.\n\nAnálisis cuantitativos proyectan una posible corrección en el papel durante la próxima rueda en Wall Street, que se trasladaría a los tenedores de CEDEARs en el mercado local. Fondos institucionales habrían iniciado coberturas ante el riesgo de una revisión a la baja del guidance.\n\nEl impacto en los CEDEARs podría extenderse {durh:.0f} horas. Inversores conservadores podrían considerar reducir exposición y esperar mayor claridad sobre el ciclo de tasas antes de reposicionarse.",
            f"Señales de cautela en torno a {empresa}: analistas anticipan que la próxima presentación de resultados podría decepcionar al mercado. Las estimaciones del consenso fueron revisadas a la baja por tres casas de research internacionales, lo que presiona el precio objetivo del papel.\n\nLa rotación desde growth hacia sectores defensivos que se observa en Wall Street podría afectar especialmente a {empresa}, cuya valuación depende en mayor medida de flujos de caja proyectados a largo plazo. Este movimiento se trasladaría a los CEDEARs de {ticker} en Buenos Aires.\n\nEl deterioro podría materializarse en las próximas {durh:.0f} horas. Se sugiere monitorear el pre-market en EE.UU. antes de tomar decisiones de posición.",
        ]
        titulos = titulos_suba if sube else titulos_baja
        contenidos = contenidos_suba if sube else contenidos_baja

    elif es_fci:
        titulos_suba = [
            f"Vencimientos del Tesoro anticipan mayor rendimiento para fondos money market",
            f"{nombre}: flujo de pesos hacia FCI podría elevar el retorno unitario",
        ]
        titulos_baja = [
            f"Mayor liquidez del sistema presionaría a la baja el rendimiento de {nombre}",
            f"BCRA evaluaría baja de tasas: FCI de renta fija como {ticker} en zona de ajuste",
        ]
        contenidos_suba = [
            f"El mercado de dinero anticipa una mejora en el rendimiento de los fondos comunes de inversión de corto plazo. {nombre} ({ticker}) podría beneficiarse de los vencimientos de letras del Tesoro previstos para las próximas horas, que reinvertidos elevarían la TNA efectiva del portfolio.\n\nEl flujo hacia instrumentos de alta liquidez en pesos se viene acelerando, ya que inversores buscan cobertura frente a la volatilidad del tipo de cambio. Esta demanda adicional permitiría al fondo absorber suscripciones sin deteriorar el rendimiento unitario.\n\nEl efecto positivo sobre el valor de cuotaparte podría verse reflejado en las próximas {durh:.0f} horas. Para perfiles conservadores, los FCI money market siguen siendo la opción más eficiente para administrar el cash de corto plazo.",
        ]
        contenidos_baja = [
            f"El mercado anticipa un ajuste técnico en el rendimiento de los fondos de renta fija de corto plazo. {nombre} ({ticker}) podría verse afectado por una mayor oferta de pesos en el sistema financiero tras el pago de haberes y vencimientos impositivos, que comprimen las tasas de caución y LECAPs de cortísimo plazo.\n\nEl BCRA estaría evaluando una reducción de la tasa de política monetaria ante señales de desaceleración inflacionaria, lo que trasladaría hacia abajo los rendimientos de los activos que componen el portfolio del fondo.\n\nEl ajuste se estima transitorio y podría materializarse en las próximas {durh:.0f} horas. Una vez que el mercado absorba el exceso de liquidez, el rendimiento debería estabilizarse en niveles acordes a la tasa de referencia.",
        ]
        titulos = titulos_suba if sube else titulos_baja
        contenidos = contenidos_suba if sube else contenidos_baja

    else:
        # Acciones — usar sector para personalizar
        sector_contextos = {
            "Bancario": ("el sistema financiero", "resultados del sistema bancario", "spread de tasas activas/pasivas", "cartera de créditos"),
            "Energía": ("el sector energético", "precios del crudo y el gas natural", "tarifas de energía eléctrica", "producción de Vaca Muerta"),
            "Telecomunicaciones": ("el sector de telecomunicaciones", "penetración de banda ancha y móvil", "ARPU trimestral", "inversión en infraestructura 5G"),
            "Materiales": ("el sector de materiales básicos", "precios de commodities industriales", "demanda de acero y aluminio de China", "cotización del hierro"),
            "Consumo": ("el sector de consumo masivo", "consumo privado y poder adquisitivo", "ventas minoristas del mes", "índice de confianza del consumidor"),
            "Agro": ("el sector agropecuario", "precios de granos en el MATBA-ROFEX", "tipo de cambio diferencial agro", "campaña gruesa en curso"),
        }
        ctx_sector, driver1, driver2, driver3 = sector_contextos.get(sector, ("el mercado de capitales", "las condiciones macroeconómicas", "el contexto de tasas", "el flujo de inversión extranjera"))

        titulos_suba = [
            f"Dato clave de {driver1} podría impulsar a {nombre} en las próximas horas",
            f"Analistas anticipan rally en {ticker} ante mejora en perspectivas de {ctx_sector}",
            f"{nombre}: publicación de resultados trimestrales podría superar estimaciones",
            f"Flujo comprador esperado en {ticker} tras señales positivas en {ctx_sector}",
            f"Acuerdo sectorial potenciaría los márgenes de {nombre} según research local",
        ]
        titulos_baja = [
            f"Dato adverso de {driver1} generaría presión sobre {nombre}",
            f"Analistas advierten sobre riesgo de corrección en {ticker}",
            f"{nombre}: resultados trimestrales podrían decepcionar al consenso",
            f"Rotación sectorial amenaza a {ticker}: inversores podrían reducir exposición",
            f"Perspectivas de {ctx_sector} generan cautela en torno a {nombre}",
        ]
        contenidos_suba = [
            f"El mercado anticipa con optimismo la publicación del dato de {driver1}, que podría sorprender positivamente al consenso. Analistas locales proyectan que {nombre} ({ticker}) sería uno de los papeles más beneficiados dentro de {ctx_sector} dado su exposición directa a esta variable.\n\nResearch houses locales habrían revisado al alza sus precios objetivo para el papel, citando mejoras en {driver2} que ampliarían los márgenes operativos de la compañía en el próximo trimestre. El consenso anticipa un EPS por encima de las estimaciones previas.\n\nEl movimiento podría materializarse en las próximas {durh:.0f} horas, una vez que el dato se confirme. Inversores con posición en {ticker} deberán monitorear el volumen de operaciones como señal de que hay convicción institucional detrás del movimiento.",
            f"Señales favorables se acumulan en torno a {nombre} ({ticker}). Fuentes del sector anticipan mejoras en {driver3}, variable que el mercado monitorea de cerca para proyectar la evolución de los ingresos de la compañía en los próximos trimestres.\n\nFondos de inversión locales habrían iniciado posiciones en el papel, anticipando que el catalizador podría detonarse en las próximas horas. La acción venía acumulando presión compradora en las últimas ruedas, con volumen creciente pero precio contenido por resistencia técnica.\n\nSi el dato confirma las expectativas del mercado, la resistencia podría quebrarse y acelerar el movimiento alcista durante las próximas {durh:.0f} horas. Analistas técnicos marcan ${body.precio_objetivo:,.0f} como nivel objetivo de corto plazo.",
        ]
        contenidos_baja = [
            f"Señales de alerta se acumulan en torno a {nombre} ({ticker}). La publicación esperada del dato de {driver1} podría decepcionar al consenso de analistas, generando una reacción vendedora en el papel durante las próximas horas.\n\nFondos institucionales habrían comenzado a reducir su exposición en {ctx_sector} ante la perspectiva de que {driver2} se deteriore más de lo proyectado. Esta rotación hacia sectores defensivos podría amplificarse si el dato confirma las señales negativas.\n\nEl riesgo de corrección podría materializarse en las próximas {durh:.0f} horas. Analistas técnicos señalan que una caída bajo el soporte actual abriría el camino hacia niveles significativamente inferiores, por lo que recomiendan precaución antes de incrementar posición.",
            f"El mercado anticipa un dato adverso de {driver1} que presionaría a {nombre} ({ticker}) en la próxima rueda. Tres casas de research redujeron sus estimaciones para el sector en las últimas 24 horas, citando deterioro en {driver3} y un contexto macro más desafiante de lo previsto.\n\nInversores institucionales ya habrían iniciado coberturas sobre el papel, anticipando que los resultados trimestrales podrían quedar por debajo del consenso. La relación precio/valor libro actual ofrecería poco margen de seguridad si las estimaciones continúan revisándose a la baja.\n\nEl efecto podría extenderse {durh:.0f} horas, dependiendo de cómo reaccione el contexto macro regional. Se aconseja esperar confirmación del dato antes de tomar decisiones de posición en {ticker}.",
        ]
        titulos = titulos_suba if sube else titulos_baja
        contenidos = contenidos_suba if sube else contenidos_baja

    titulo = random.choice(titulos)
    contenido = random.choice(contenidos)

    return {
        "titulo": titulo,
        "contenido": contenido,
        "impacto_pct": impacto_pct,
        "impacto_tipo": impacto_tipo,
        "delta_pct": delta_pct,
    }
