# Simulador de Cartera v2 — Guía de deploy

## 1. Subir a GitHub

```bash
cd simulador-v2
git init
git add .
git commit -m "Simulador v2 — backend FastAPI + frontend React"
git remote add origin https://github.com/TU_USUARIO/simulador-cartera-v2.git
git push -u origin main
```

## 2. Deploy del backend en Render

1. Ir a https://render.com → **New** → **Web Service**
2. Conectar el repo de GitHub
3. Configuración:
   - **Build Command:** `pip install -r backend/requirements.txt`
   - **Start Command:** `cd backend && uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Plan:** Free
4. En **Disks** (para persistencia de la DB SQLite):
   - Mount path: `/opt/render/project/src/backend`
   - Size: 1 GB
5. Click **Create Web Service**
6. Anotar la URL (ej: `https://simulador-unicen.onrender.com`)

> ⚠️ **Importante:** Sin el Disk configurado, la DB se resetea cada deploy.
> El plan free de Render permite 1 disco de 1 GB.

## 3. Configurar la URL en el frontend

Editar `frontend/index.html`, línea:
```js
const API_BASE = window.SIMULADOR_API_URL || "https://simulador-unicen.onrender.com";
```
Reemplazar `simulador-unicen.onrender.com` con la URL real del servicio.

## 4. Subir el frontend a Moodle

El archivo `frontend/index.html` es autónomo. En Moodle:
1. Agregar recurso → **Archivo**
2. Subir `index.html`
3. Habilitar "Forzar descarga" = **No** (se abre en el navegador)

Alternativamente, alojarlo en cualquier hosting estático (Netlify, GitHub Pages).

## 5. Credenciales por defecto

- **Docente:** usuario `docente`, contraseña `simulador2024`
  (cambiarla desde el panel de configuración en producción)
- **Grupos:** el código de acceso se genera automáticamente al crear el grupo

## 6. Flujo de uso

1. El docente crea los grupos y obtiene los códigos de acceso
2. El docente carga la lista de alumnos (CSV o manual)
3. El docente programa las noticias con fecha/hora de publicación
4. Cada grupo ingresa con su código → completa la encuesta de perfil → opera
5. El docente consulta reportes en cualquier momento

## Estructura del proyecto

```
simulador-v2/
├── backend/
│   ├── main.py              # FastAPI app
│   ├── models.py            # SQLAlchemy models + seed
│   ├── auth.py              # JWT auth
│   ├── market.py            # Random walk de precios
│   ├── perfil_riesgo.py     # Encuesta + validación de coherencia
│   ├── requirements.txt
│   └── routers/
│       ├── auth.py          # /api/auth/...
│       ├── docente.py       # /api/docente/...
│       └── grupos.py        # /api/grupos/...
├── frontend/
│   └── index.html           # React app (autónoma, sin build)
└── render.yaml              # Configuración Render
```
