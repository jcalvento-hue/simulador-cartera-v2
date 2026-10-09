"""
Modelos de datos — Simulador de Cartera v2
SQLite via SQLAlchemy (un único archivo simulador.db)
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

Base = declarative_base()


class Configuracion(Base):
    """Parámetros globales de la experiencia (uno por simulación)."""
    __tablename__ = "configuracion"
    id = Column(Integer, primary_key=True, default=1)
    nombre_experiencia = Column(String(200), default="Simulador de Cartera")
    capital_inicial = Column(Float, default=1_000_000.0)
    comision = Column(Float, default=0.005)          # 0.5%
    tasa_caucion = Column(Float, default=0.60)       # TNA 60% para cauciones
    activo = Column(Boolean, default=True)
    creado_en = Column(DateTime, default=datetime.utcnow)


class Docente(Base):
    """Cuenta del docente (una sola, con contraseña hasheada)."""
    __tablename__ = "docentes"
    id = Column(Integer, primary_key=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    nombre = Column(String(200))


class Alumno(Base):
    """Listado de alumnos cargado por el docente."""
    __tablename__ = "alumnos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(200), nullable=False)
    apellido = Column(String(200), nullable=False)
    legajo = Column(String(50), unique=True)
    email = Column(String(200))
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=True)
    grupo = relationship("Grupo", back_populates="alumnos")


class Grupo(Base):
    """Grupo de alumnos — unidad operativa del simulador."""
    __tablename__ = "grupos"
    id = Column(Integer, primary_key=True)
    nombre = Column(String(100), nullable=False, unique=True)
    codigo_acceso = Column(String(20), nullable=False, unique=True)   # login del grupo
    capital_disponible = Column(Float, default=1_000_000.0)
    perfil_riesgo = Column(String(20), nullable=True)  # conservador/moderado/agresivo
    encuesta_completada = Column(Boolean, default=False)
    creado_en = Column(DateTime, default=datetime.utcnow)

    alumnos = relationship("Alumno", back_populates="grupo")
    posiciones = relationship("Posicion", back_populates="grupo")
    operaciones = relationship("Operacion", back_populates="grupo")


class Instrumento(Base):
    """Activos disponibles para operar."""
    __tablename__ = "instrumentos"
    id = Column(Integer, primary_key=True)
    ticker = Column(String(20), unique=True, nullable=False)
    nombre = Column(String(200), nullable=False)
    tipo = Column(String(50), default="accion")          # accion / bono / cedear
    precio_inicial = Column(Float, nullable=False)
    precio_actual = Column(Float, nullable=False)
    volatilidad = Column(Float, default=0.02)            # desviación estándar del random walk
    activo = Column(Boolean, default=True)

    posiciones = relationship("Posicion", back_populates="instrumento")
    operaciones = relationship("Operacion", back_populates="instrumento")
    precios = relationship("HistorialPrecios", back_populates="instrumento")


class HistorialPrecios(Base):
    """Serie de precios generada por el random walk."""
    __tablename__ = "historial_precios"
    id = Column(Integer, primary_key=True)
    instrumento_id = Column(Integer, ForeignKey("instrumentos.id"), nullable=False)
    precio = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    instrumento = relationship("Instrumento", back_populates="precios")


class Posicion(Base):
    """Tenencia actual de un grupo en un instrumento."""
    __tablename__ = "posiciones"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False)
    instrumento_id = Column(Integer, ForeignKey("instrumentos.id"), nullable=False)
    cantidad = Column(Integer, default=0)
    precio_promedio = Column(Float, default=0.0)   # precio promedio de compra

    grupo = relationship("Grupo", back_populates="posiciones")
    instrumento = relationship("Instrumento", back_populates="posiciones")


class Operacion(Base):
    """Registro histórico de cada orden ejecutada."""
    __tablename__ = "operaciones"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False)
    instrumento_id = Column(Integer, ForeignKey("instrumentos.id"), nullable=False)
    tipo = Column(String(10), nullable=False)        # compra / venta
    cantidad = Column(Integer, nullable=False)
    precio = Column(Float, nullable=False)
    comision = Column(Float, nullable=False)
    monto_total = Column(Float, nullable=False)      # cantidad * precio + comision
    noticia_id = Column(Integer, ForeignKey("noticias.id"), nullable=True)  # noticia vigente al operar
    advertencia_perfil = Column(Boolean, default=False)  # si disparó advertencia
    timestamp = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", back_populates="operaciones")
    instrumento = relationship("Instrumento", back_populates="operaciones")
    noticia = relationship("Noticia")


class Noticia(Base):
    """Noticias / análisis técnico publicados por el docente."""
    __tablename__ = "noticias"
    id = Column(Integer, primary_key=True)
    titulo = Column(String(300), nullable=False)
    contenido = Column(Text, nullable=False)
    tipo = Column(String(30), default="fundamental")   # fundamental / tecnico
    ticker_relacionado = Column(String(20), nullable=True)  # instrumento al que refiere
    publicado_en = Column(DateTime, nullable=False)    # cuándo se hace visible a los grupos
    creado_en = Column(DateTime, default=datetime.utcnow)
    activa = Column(Boolean, default=True)

    lecturas = relationship("LecturaNoticia", back_populates="noticia")


class LecturaNoticia(Base):
    """Registro de qué grupos leyeron cada noticia."""
    __tablename__ = "lecturas_noticias"
    id = Column(Integer, primary_key=True)
    noticia_id = Column(Integer, ForeignKey("noticias.id"), nullable=False)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False)
    leida_en = Column(DateTime, default=datetime.utcnow)

    noticia = relationship("Noticia", back_populates="lecturas")
    grupo = relationship("Grupo")


class Caucion(Base):
    """Caución bursátil colocada por un grupo."""
    __tablename__ = "cauciones"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False)
    monto = Column(Float, nullable=False)            # capital colocado
    tna = Column(Float, nullable=False)              # tasa nominal anual al momento de constituir
    plazo_dias = Column(Integer, nullable=False)     # 1, 7, 30, 60, 90
    intereses = Column(Float, nullable=False)        # intereses a cobrar al vencimiento
    monto_total = Column(Float, nullable=False)      # monto + intereses
    constituida_en = Column(DateTime, default=datetime.utcnow)
    vence_en = Column(DateTime, nullable=False)
    cobrada = Column(Boolean, default=False)         # True cuando el loop la acreditó

    grupo = relationship("Grupo")


class RespuestaEncuesta(Base):
    """Respuestas del grupo a la encuesta de perfil de riesgo."""
    __tablename__ = "respuestas_encuesta"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False)
    pregunta_num = Column(Integer, nullable=False)
    respuesta = Column(String(10), nullable=False)    # a / b / c
    puntaje = Column(Integer, nullable=False)
    respondida_en = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo")


# ── Engine y sesión ──────────────────────────────────────────────────────────

DATABASE_URL = "sqlite:///./simulador.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Crea las tablas y carga datos iniciales si la DB está vacía."""
    Base.metadata.create_all(bind=engine)
    _seed(SessionLocal())


def _seed(db):
    """Datos iniciales: docente admin + instrumentos."""
    import bcrypt as _bcrypt

    # Docente por defecto
    if not db.query(Docente).first():
        pw_hash = _bcrypt.hashpw(b"simulador2024", _bcrypt.gensalt()).decode()
        db.add(Docente(
            username="docente",
            password_hash=pw_hash,
            nombre="Docente"
        ))

    # Configuración
    if not db.query(Configuracion).first():
        db.add(Configuracion())

    # Instrumentos: acciones, bonos, CEDEARs y FCI
    if not db.query(Instrumento).first():
        instrumentos = [
            # ticker, nombre, tipo, precio, volatilidad
            # ── Acciones líderes Merval ────────────────────────────────────────
            ("GGAL",   "Grupo Financiero Galicia",         "accion",   2580.0, 0.025),
            ("YPF",    "YPF S.A.",                         "accion",   1450.0, 0.030),
            ("BMA",    "Banco Macro",                      "accion",   3200.0, 0.022),
            ("PAMP",   "Pampa Energía",                    "accion",    890.0, 0.028),
            ("TXAR",   "Ternium Argentina",                "accion",   1120.0, 0.024),
            ("ALUA",   "Aluar Aluminio",                   "accion",    580.0, 0.020),
            ("SUPV",   "Grupo Supervielle",                "accion",   1850.0, 0.032),
            ("CEPU",   "Central Puerto",                   "accion",    730.0, 0.026),
            ("LOMA",   "Loma Negra",                       "accion",    670.0, 0.023),
            ("BBAR",   "BBVA Argentina",                   "accion",   2100.0, 0.027),
            ("TECO2",  "Telecom Argentina",                "accion",   1320.0, 0.022),
            ("CRES",   "Cresud",                           "accion",    980.0, 0.028),
            # ── Bonos soberanos ───────────────────────────────────────────────
            ("AL30",   "Bono Soberano USD Ley Arg. 2030",  "bono",    51500.0, 0.012),
            ("GD30",   "Bono Soberano USD Ley NY 2030",    "bono",    53200.0, 0.010),
            ("AL35",   "Bono Soberano USD Ley Arg. 2035",  "bono",    43800.0, 0.013),
            ("AE38",   "Bono Soberano USD Ley NY 2038",    "bono",    48100.0, 0.011),
            ("TX26",   "Bono CER 2026",                    "bono",    97500.0, 0.008),
            ("T2X5",   "Bono CER 2025",                    "bono",   103200.0, 0.006),
            # ── CEDEARs ───────────────────────────────────────────────────────
            ("AAPL",   "Apple Inc. (CEDEAR)",              "cedear",  18200.0, 0.018),
            ("GOOGL",  "Alphabet Inc. (CEDEAR)",           "cedear",  15600.0, 0.020),
            ("AMZN",   "Amazon.com Inc. (CEDEAR)",         "cedear",  17400.0, 0.019),
            ("MSFT",   "Microsoft Corp. (CEDEAR)",         "cedear",  39800.0, 0.016),
            ("TSLA",   "Tesla Inc. (CEDEAR)",              "cedear",  22300.0, 0.040),
            ("BRKB",   "Berkshire Hathaway B (CEDEAR)",    "cedear",  43100.0, 0.014),
            # ── FCI — precio en cuota parte (ARS) ────────────────────────────
            # Volatilidad 0 = sin random walk, precio sube por drift en market.py
            ("FCICONV", "FCI Conservador — Money Market",  "fci",      1000.0, 0.000),
            ("FCIMOD",  "FCI Moderado — Renta Fija",       "fci",      1000.0, 0.003),
            ("FCIAGR",  "FCI Agresivo — Renta Variable",   "fci",      1000.0, 0.008),
        ]
        for ticker, nombre, tipo, precio, vol in instrumentos:
            db.add(Instrumento(
                ticker=ticker, nombre=nombre, tipo=tipo,
                precio_inicial=precio, precio_actual=precio, volatilidad=vol
            ))

    db.commit()
    db.close()
