"""
Modelos de datos — Simulador de Cartera v2
SQLite via SQLAlchemy (un único archivo simulador.db)
"""
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, JSON, text
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
    tipo = Column(String(50), default="accion")          # accion / bono / cedear / fci
    sector = Column(String(100), nullable=True)          # sector de industria
    tendencia_esperada = Column(String(20), nullable=True)  # alcista / bajista / neutro
    precio_inicial = Column(Float, nullable=False)
    precio_actual = Column(Float, nullable=False)
    precio_sesion = Column(Float, nullable=True)         # precio al inicio de la sesión actual
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


class PerfilGrupo(Base):
    """
    Perfil de inversión asignado por el docente a cada grupo.
    Reemplaza a la encuesta de autoevaluación.
    """
    __tablename__ = "perfil_grupo"
    id = Column(Integer, primary_key=True)
    grupo_id = Column(Integer, ForeignKey("grupos.id"), nullable=False, unique=True)
    # Estilo general
    estilo = Column(String(20), default="moderado")     # conservador / moderado / agresivo / libre
    # Límites de concentración por activo
    max_pct_por_activo = Column(Float, nullable=True)   # ej: 0.15 = 15%
    # Límites por sector
    max_pct_por_sector = Column(Float, nullable=True)   # ej: 0.30 = 30%
    # Diversificación mínima
    min_activos = Column(Integer, nullable=True)        # nro mínimo de activos distintos
    min_sectores = Column(Integer, nullable=True)       # nro mínimo de sectores
    # Límites por tipo de instrumento (proporciones sobre capital total)
    min_pct_renta_fija = Column(Float, nullable=True)
    max_pct_renta_fija = Column(Float, nullable=True)
    min_pct_renta_variable = Column(Float, nullable=True)
    max_pct_renta_variable = Column(Float, nullable=True)
    min_pct_liquidez = Column(Float, nullable=True)
    max_pct_liquidez = Column(Float, nullable=True)
    # Seguir tendencia configurada en cada instrumento
    respetar_tendencia = Column(Boolean, default=False)
    # Notas libres del docente para el grupo
    notas = Column(Text, nullable=True)
    asignado_en = Column(DateTime, default=datetime.utcnow)

    grupo = relationship("Grupo", backref="perfil_docente")


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
    # Migraciones: agregar columnas nuevas si no existen (safe — falla silenciosamente si ya existen)
    migrations = [
        "ALTER TABLE instrumentos ADD COLUMN precio_sesion FLOAT",
        "ALTER TABLE instrumentos ADD COLUMN sector VARCHAR(100)",
        "ALTER TABLE instrumentos ADD COLUMN tendencia_esperada VARCHAR(20)",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # ya existe
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
            # ticker, nombre, tipo, precio, volatilidad, sector
            # ── Acciones líderes Merval ────────────────────────────────────────
            ("GGAL",   "Grupo Financiero Galicia",         "accion",   2580.0, 0.025, "Financiero"),
            ("YPF",    "YPF S.A.",                         "accion",   1450.0, 0.030, "Energía"),
            ("BMA",    "Banco Macro",                      "accion",   3200.0, 0.022, "Financiero"),
            ("PAMP",   "Pampa Energía",                    "accion",    890.0, 0.028, "Energía"),
            ("TXAR",   "Ternium Argentina",                "accion",   1120.0, 0.024, "Materiales"),
            ("ALUA",   "Aluar Aluminio",                   "accion",    580.0, 0.020, "Materiales"),
            ("SUPV",   "Grupo Supervielle",                "accion",   1850.0, 0.032, "Financiero"),
            ("CEPU",   "Central Puerto",                   "accion",    730.0, 0.026, "Utilities"),
            ("LOMA",   "Loma Negra",                       "accion",    670.0, 0.023, "Materiales"),
            ("BBAR",   "BBVA Argentina",                   "accion",   2100.0, 0.027, "Financiero"),
            ("TECO2",  "Telecom Argentina",                "accion",   1320.0, 0.022, "Telecomunicaciones"),
            ("CRES",   "Cresud",                           "accion",    980.0, 0.028, "Agropecuario"),
            # ── Bonos soberanos ───────────────────────────────────────────────
            ("AL30",   "Bono Soberano USD Ley Arg. 2030",  "bono",    51500.0, 0.012, "Renta Fija Soberana"),
            ("GD30",   "Bono Soberano USD Ley NY 2030",    "bono",    53200.0, 0.010, "Renta Fija Soberana"),
            ("AL35",   "Bono Soberano USD Ley Arg. 2035",  "bono",    43800.0, 0.013, "Renta Fija Soberana"),
            ("AE38",   "Bono Soberano USD Ley NY 2038",    "bono",    48100.0, 0.011, "Renta Fija Soberana"),
            ("TX26",   "Bono CER 2026",                    "bono",    97500.0, 0.008, "Renta Fija CER"),
            ("T2X5",   "Bono CER 2025",                    "bono",   103200.0, 0.006, "Renta Fija CER"),
            # ── CEDEARs ───────────────────────────────────────────────────────
            ("AAPL",   "Apple Inc. (CEDEAR)",              "cedear",  18200.0, 0.018, "Tecnología"),
            ("GOOGL",  "Alphabet Inc. (CEDEAR)",           "cedear",  15600.0, 0.020, "Tecnología"),
            ("AMZN",   "Amazon.com Inc. (CEDEAR)",         "cedear",  17400.0, 0.019, "Consumo Discrecional"),
            ("MSFT",   "Microsoft Corp. (CEDEAR)",         "cedear",  39800.0, 0.016, "Tecnología"),
            ("TSLA",   "Tesla Inc. (CEDEAR)",              "cedear",  22300.0, 0.040, "Consumo Discrecional"),
            ("BRKB",   "Berkshire Hathaway B (CEDEAR)",    "cedear",  43100.0, 0.014, "Financiero"),
            # ── FCI — precio en cuota parte (ARS) ────────────────────────────
            # Volatilidad 0 = sin random walk, precio sube por drift en market.py
            ("FCICONV", "FCI Conservador — Money Market",  "fci",      1000.0, 0.000, "Liquidez"),
            ("FCIMOD",  "FCI Moderado — Renta Fija",       "fci",      1000.0, 0.003, "Renta Fija"),
            ("FCIAGR",  "FCI Agresivo — Renta Variable",   "fci",      1000.0, 0.008, "Renta Variable"),
        ]
        for ticker, nombre, tipo, precio, vol, sector in instrumentos:
            db.add(Instrumento(
                ticker=ticker, nombre=nombre, tipo=tipo,
                precio_inicial=precio, precio_actual=precio, volatilidad=vol,
                sector=sector
            ))

    # Grupos de ejemplo
    if not db.query(Grupo).first():
        import string as _string, secrets as _secrets
        def _cod():
            return "".join(_secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(6))
        config = db.query(Configuracion).first()
        capital = config.capital_inicial if config else 1_000_000.0
        grupos_seed = [
            ("Grupo A", _cod()),
            ("Grupo B", _cod()),
            ("Grupo C", _cod()),
            ("Grupo D", _cod()),
            ("Grupo E", _cod()),
        ]
        for nombre, codigo in grupos_seed:
            db.add(Grupo(nombre=nombre, codigo_acceso=codigo, capital_disponible=capital))
        db.flush()

    # Alumnos de ejemplo (sin grupo asignado)
    if not db.query(Alumno).first():
        alumnos_seed = [
            ("Ana",       "García",    "12001", "ana.garcia@estudiantes.edu.ar"),
            ("Lucía",     "Martínez",  "12002", "lucia.martinez@estudiantes.edu.ar"),
            ("Tomás",     "Rodríguez", "12003", "tomas.rodriguez@estudiantes.edu.ar"),
            ("Valentina", "López",     "12004", "valentina.lopez@estudiantes.edu.ar"),
            ("Matías",    "González",  "12005", "matias.gonzalez@estudiantes.edu.ar"),
            ("Sofía",     "Pérez",     "12006", "sofia.perez@estudiantes.edu.ar"),
            ("Juan",      "Sánchez",   "12007", "juan.sanchez@estudiantes.edu.ar"),
            ("Camila",    "Romero",    "12008", "camila.romero@estudiantes.edu.ar"),
            ("Nicolás",   "Torres",    "12009", "nicolas.torres@estudiantes.edu.ar"),
            ("Florencia", "Díaz",      "12010", "florencia.diaz@estudiantes.edu.ar"),
        ]
        for nombre, apellido, legajo, email in alumnos_seed:
            db.add(Alumno(nombre=nombre, apellido=apellido, legajo=legajo, email=email))

    # Noticias de ejemplo
    if not db.query(Noticia).first():
        noticias_seed = [
            {
                "titulo": "YPF anuncia inversión en Vaca Muerta por USD 2.000M",
                "contenido": "La empresa estatal YPF confirmó una inversión de USD 2.000 millones en el yacimiento de Vaca Muerta para los próximos 18 meses. Los analistas estiman un impacto positivo en el precio de la acción del 8-12% en el corto plazo.",
                "tipo": "fundamental",
                "ticker_relacionado": "YPF",
                "publicado_en": datetime(2024, 10, 1, 10, 0),
            },
            {
                "titulo": "GGAL: señal de ruptura de resistencia en $2.800",
                "contenido": "El gráfico de Galicia muestra una formación de triángulo ascendente con resistencia en $2.800. Un cierre por encima de ese nivel con volumen confirmaría la continuación alcista hacia el objetivo de $3.200.",
                "tipo": "tecnico",
                "ticker_relacionado": "GGAL",
                "publicado_en": datetime(2024, 10, 2, 9, 30),
            },
            {
                "titulo": "Riesgo país baja de 1.000 puntos — efecto en bonos soberanos",
                "contenido": "El riesgo país argentino perforó la barrera psicológica de los 1.000 puntos básicos por primera vez desde 2019. El movimiento impactó positivamente en AL30 y GD30, que subieron más del 5% en la jornada.",
                "tipo": "fundamental",
                "ticker_relacionado": "AL30",
                "publicado_en": datetime(2024, 10, 3, 11, 0),
            },
            {
                "titulo": "Sector financiero: análisis técnico de BMA y BBAR",
                "contenido": "BMA cotiza en la parte alta de un canal alcista de largo plazo. RSI en 68 sugiere acercamiento a zona de sobrecompra. BBAR, en cambio, acaba de rebotar en soporte de $1.950 con RSI en 42, generando señal de entrada.",
                "tipo": "tecnico",
                "ticker_relacionado": "BMA",
                "publicado_en": datetime(2024, 10, 5, 14, 0),
            },
            {
                "titulo": "CEDEARs: Apple y Microsoft reaccionan tras resultados trimestrales",
                "contenido": "Apple y Microsoft publicaron resultados del tercer trimestre superando expectativas del mercado. El tipo de cambio implícito del CEDEAR se mantiene estable, lo que implica que la suba de las acciones en Wall Street debería trasladarse directamente al precio local.",
                "tipo": "fundamental",
                "ticker_relacionado": "AAPL",
                "publicado_en": datetime(2024, 10, 7, 10, 30),
            },
        ]
        for n in noticias_seed:
            db.add(Noticia(**n))

    db.commit()
    db.close()
