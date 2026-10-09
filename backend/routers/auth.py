"""Router de autenticación — docente y grupos"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from pydantic import BaseModel

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from models import Docente, Grupo, get_db
from auth import verify_password, create_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class GrupoLoginIn(BaseModel):
    codigo_acceso: str


@router.post("/docente/login")
def login_docente(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    docente = db.query(Docente).filter(Docente.username == form.username).first()
    if not docente or not verify_password(form.password, docente.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales incorrectas")

    token = create_token({"sub": docente.id, "role": "docente"})
    return {"access_token": token, "token_type": "bearer", "role": "docente", "nombre": docente.nombre}


@router.post("/grupo/login")
def login_grupo(body: GrupoLoginIn, db: Session = Depends(get_db)):
    grupo = db.query(Grupo).filter(Grupo.codigo_acceso == body.codigo_acceso.upper()).first()
    if not grupo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Código de acceso inválido")

    token = create_token({"sub": grupo.id, "role": "grupo"})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": "grupo",
        "grupo_id": grupo.id,
        "nombre": grupo.nombre,
        "encuesta_completada": grupo.encuesta_completada,
        "perfil_riesgo": grupo.perfil_riesgo,
    }
