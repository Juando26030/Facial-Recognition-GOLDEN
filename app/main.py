from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.routers import api
from app.database import engine
from app.models import Base

# Crea las tablas de SQL automáticamente en la base de datos
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Golden Biometrics SaaS")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Conectamos las rutas de nuestra API
app.include_router(api.router, prefix="/api")

@app.get("/")
async def read_index(request: Request):
    # Solución al error de versión: uso de parámetros nombrados (request=request, name="...")
    return templates.TemplateResponse(request=request, name="index.html")