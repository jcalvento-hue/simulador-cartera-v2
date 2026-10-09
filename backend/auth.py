"""
Autenticación JWT — docente y grupos
"""
from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from sqlalchemy.orm import Session
from models import Docente, Grupo, get_db

SECRET_KEY = "simulador-unicen-secret-2024-change-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 12

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/docente/login", auto_error=False)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode() if isinstance(hashed, str) else hashed)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def create_token(data: dict, expires_hours: int = ACCESS_TOKEN_EXPIRE_HOURS) -> str:
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=expires_hours)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── Dependencias FastAPI ──────────────────────────────────────────────────────

def get_current_docente(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Docente:
    payload = decode_token(token) if token else None
    if not payload or payload.get("role") != "docente":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado")
    docente = db.query(Docente).filter(Docente.id == payload.get("sub")).first()
    if not docente:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Docente no encontrado")
    return docente


def get_current_grupo(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Grupo:
    payload = decode_token(token) if token else None
    if not payload or payload.get("role") != "grupo":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado")
    grupo = db.query(Grupo).filter(Grupo.id == payload.get("sub")).first()
    if not grupo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Grupo no encontrado")
    return grupo


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
):
    """Retorna docente o grupo, lo que sea."""
    payload = decode_token(token) if token else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autorizado")
    role = payload.get("role")
    if role == "docente":
        return db.query(Docente).filter(Docente.id == payload.get("sub")).first()
    elif role == "grupo":
        return db.query(Grupo).filter(Grupo.id == payload.get("sub")).first()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")
