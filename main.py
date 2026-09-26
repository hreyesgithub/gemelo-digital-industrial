"""
main.py
=======
Gemelo Digital · Backend FastAPI
---------------------------------
- Sirve el frontend SPA desde /static
- Expone /ws (WebSocket) para telemetría en tiempo real y comandos de control
- Expone /api/* como API REST (comandos y fallback)
- Persiste histórico y alertas en Supabase
"""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from utilidades.database import Database
from utilidades.simulator import ProductionLine

# ------------------------------------------------------------------------------
#  CONFIGURACIÓN
# ------------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("gemelo-digital")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
TICK_SECONDS = float(os.getenv("TICK_SECONDS", "1.0"))
PERSIST_EVERY = int(os.getenv("PERSIST_EVERY", "5"))

db = Database(SUPABASE_URL, SUPABASE_KEY)
linea = ProductionLine(linea_id="LINEA-01")

ACCIONES_VALIDAS = {
    "detener_linea",
    "stop_line",
    "emergencia",
    "reiniciar_linea",
    "start_line",
    "reiniciar_maquina",
    "restart_machine",
    "mantenimiento_maquina",
    "maintenance_machine",
}


# ------------------------------------------------------------------------------
#  GESTOR DE CONEXIONES WEBSOCKET
# ------------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: List[WebSocket] = []
        self.lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self.lock:
            self.active.append(ws)
        logger.info("Cliente WebSocket conectado. Total: %d", len(self.active))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)
        logger.info("Cliente WebSocket desconectado. Total: %d", len(self.active))

    async def broadcast(self, message: dict) -> None:
        async with self.lock:
            targets = list(self.active)
        if not targets:
            return

        payload = json.dumps(message, default=str)
        caidos = []
        for ws in targets:
            try:
                await ws.send_text(payload)
            except Exception:
                caidos.append(ws)
        for ws in caidos:
            await self.disconnect(ws)


manager = ConnectionManager()


# ------------------------------------------------------------------------------
#  LÓGICA DE COMANDOS (compartida entre WebSocket y REST)
# ------------------------------------------------------------------------------
def ejecutar_comando(accion: str, maquina_id: Optional[str], motivo: str) -> dict:
    accion_norm = (accion or "").strip().lower()

    if accion_norm not in ACCIONES_VALIDAS:
        raise ValueError(f"Acción no reconocida: '{accion}'")

    if accion_norm in ("detener_linea", "stop_line", "emergencia"):
        eventos = linea.detener_linea(motivo or "Parada de emergencia")
        resultado = "Línea detenida por emergencia"

    elif accion_norm in ("reiniciar_linea", "start_line"):
        eventos = linea.reiniciar_linea(motivo or "Reinicio manual de línea")
        resultado = "Línea reiniciada"

    elif accion_norm in ("reiniciar_maquina", "restart_machine"):
        if not maquina_id:
            raise ValueError("Se requiere 'maquina_id' para reiniciar una máquina")
        eventos = linea.reiniciar_maquina(maquina_id, motivo or "Reinicio manual")
        if not eventos:
            raise ValueError(f"Máquina no encontrada: {maquina_id}")
        resultado = f"Máquina {maquina_id} reiniciada"

    else:  # mantenimiento_maquina
        if not maquina_id:
            raise ValueError("Se requiere 'maquina_id' para programar mantenimiento")
        eventos = linea.mantenimiento_maquina(
            maquina_id, motivo or "Mantenimiento manual"
        )
        if not eventos:
            raise ValueError(f"Máquina no encontrada: {maquina_id}")
        resultado = f"Máquina {maquina_id} en mantenimiento"

    return {
        "accion": accion_norm,
        "maquina_id": maquina_id,
        "motivo": motivo,
        "resultado": resultado,
        "eventos": eventos,
    }


# ------------------------------------------------------------------------------
#  MODELOS PYDANTIC
# ------------------------------------------------------------------------------
class ComandoRequest(BaseModel):
    accion: str = Field(
        ...,
        description="detener_linea | reiniciar_linea | reiniciar_maquina | mantenimiento_maquina",
    )
    maquina_id: Optional[str] = Field(None, description="ID de la máquina (M1..M5)")
    motivo: Optional[str] = Field("Operador desde dashboard")


# ------------------------------------------------------------------------------
#  BUCLE DE SIMULACIÓN
# ------------------------------------------------------------------------------
async def simulation_loop() -> None:
    logger.info(
        "Bucle de simulación iniciado (tick=%.2fs, persistencia cada %ds)",
        TICK_SECONDS,
        PERSIST_EVERY,
    )
    contador = 0
    while True:
        try:
            snapshot = linea.tick()
            await manager.broadcast(snapshot)

            contador += 1
            if contador % PERSIST_EVERY == 0:
                await db.save_historico(linea.historico_payload())

            for alerta in linea.pop_pendientes():
                await db.save_alerta(alerta)

        except asyncio.CancelledError:
            logger.info("Bucle de simulación detenido.")
            raise
        except Exception as exc:
            logger.exception("Error en el bucle de simulación: %s", exc)

        await asyncio.sleep(TICK_SECONDS)


# ------------------------------------------------------------------------------
#  CICLO DE VIDA
# ------------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    tarea = asyncio.create_task(simulation_loop())
    yield
    tarea.cancel()
    try:
        await tarea
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Gemelo Digital · Línea de Producción",
    description="Demo MVP de gemelo digital industrial con telemetría en tiempo real.",
    version="1.0.0",
    lifespan=lifespan,
)

# ------------------------------------------------------------------------------
#  CORS · configurable por entorno
#  En producción (Render) define ALLOWED_ORIGINS con los dominios de Firebase.
#  Ejemplo: ALLOWED_ORIGINS=https://venezuelainsights.com,https://tu-proyecto.web.app
# ------------------------------------------------------------------------------
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------------------
#  ENDPOINTS REST
# ------------------------------------------------------------------------------
@app.api_route("/api/health", methods=["GET", "HEAD"])
async def health():
    return {
        "status": "ok",
        "linea": linea.linea_id,
        "uptime_seg": linea.ticks,
        "clientes_ws": len(manager.active),
        "supabase_conectado": db.enabled,
        "errores_db": db.errores,
        "tick_segundos": TICK_SECONDS,
    }


@app.get("/api/snapshot")
async def snapshot():
    """Último estado completo de la línea (útil para polling o debugging)."""
    return linea.snapshot()


@app.get("/api/alertas")
async def alertas():
    return {"alertas": list(linea.alertas_recientes)}


@app.post("/api/control")
async def control(req: ComandoRequest):
    try:
        resultado = ejecutar_comando(req.accion, req.maquina_id, req.motivo or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Auditoría en Supabase
    await db.save_comando(
        {
            "linea_id": linea.linea_id,
            "maquina_id": req.maquina_id,
            "comando": req.accion,
            "motivo": req.motivo,
            "origen": "rest",
            "ejecutado": True,
        }
    )

    # Emitir telemetría inmediata a todos los clientes
    await manager.broadcast(linea.snapshot())
    return resultado


@app.post("/api/control/detener")
async def detener_linea():
    return await control(
        ComandoRequest(
            accion="detener_linea", maquina_id=None, motivo="Parada de emergencia"
        )
    )


@app.post("/api/control/reiniciar")
async def reiniciar_linea():
    return await control(
        ComandoRequest(
            accion="reiniciar_linea",
            maquina_id=None,
            motivo="Reinicio manual de línea",
        )
    )


# ------------------------------------------------------------------------------
#  WEBSOCKET (telemetría en tiempo real + comandos)
# ------------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Snapshot inmediato al conectar
        await ws.send_text(json.dumps(linea.snapshot(), default=str))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_text(
                    json.dumps({"type": "error", "detail": "JSON inválido"})
                )
                continue

            if msg.get("type") != "command":
                continue

            try:
                resultado = ejecutar_comando(
                    msg.get("accion", ""),
                    msg.get("maquina_id"),
                    msg.get("motivo", "Operador desde dashboard"),
                )
            except ValueError as exc:
                await ws.send_text(
                    json.dumps({"type": "command_error", "detail": str(exc)})
                )
                continue

            await db.save_comando(
                {
                    "linea_id": linea.linea_id,
                    "maquina_id": msg.get("maquina_id"),
                    "comando": msg.get("accion"),
                    "motivo": msg.get("motivo"),
                    "origen": "websocket",
                    "ejecutado": True,
                }
            )

            await ws.send_text(
                json.dumps({"type": "command_ack", "data": resultado}, default=str)
            )
            await manager.broadcast(linea.snapshot())

    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception as exc:
        logger.exception("Error en WebSocket: %s", exc)
        await manager.disconnect(ws)


# ------------------------------------------------------------------------------
#  FRONTEND ESTÁTICO (OPCIONAL)
#  - Si existe ./static/ → lo sirve (útil en desarrollo local).
#  - Si no existe → expone un landing JSON. El frontend real vivirá en Firebase.
# ------------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

if os.path.isdir(STATIC_DIR):
    logger.info("Sirviendo frontend desde %s", STATIC_DIR)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    logger.info("Sin carpeta static/. Modo API-only (frontend en Firebase).")

    @app.get("/")
    async def root():
        return {
            "servicio": "Gemelo Digital · API",
            "version": "1.0.0",
            "endpoints": {
                "health":    "/api/health",
                "snapshot":  "/api/snapshot",
                "alertas":   "/api/alertas",
                "control":   "/api/control",
                "websocket": "/ws",
                "docs":      "/docs",
            },
        }
