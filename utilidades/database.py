"""
backend/utilidades/database.py
===========
Cliente Supabase con degradación elegante: si no hay credenciales válidas,
el backend sigue funcionando en modo "sin persistencia" (útil para demos).
"""

import asyncio
import logging
from typing import Any, Dict

logger = logging.getLogger("gemelo-digital.db")


class Database:
    def __init__(self, url: str, key: str):
        self.enabled = bool(url and key)
        self.client = None
        self.errores = 0

        if not self.enabled:
            logger.warning(
                "SUPABASE_URL / SUPABASE_KEY no configurados. "
                "Ejecutando en modo SIN PERSISTENCIA."
            )
            return

        try:
            from supabase import create_client

            self.client = create_client(url, key)
            logger.info("Conexión Supabase inicializada correctamente.")
        except Exception as exc:  # pragma: no cover
            self.enabled = False
            logger.error("No se pudo inicializar Supabase: %s", exc)

    # --------------------------------------------------------------------------
    async def _insert(self, tabla: str, payload: Dict[str, Any]) -> None:
        client = self.client
        if not self.enabled or client is None or not payload:
            return
        try:
            # El SDK de Supabase es síncrono → lo movemos a un hilo.
            await asyncio.to_thread(
                lambda: client.table(tabla).insert(payload).execute()
            )
        except Exception as exc:
            self.errores += 1
            logger.error("Error insertando en '%s': %s", tabla, exc)

    # --------------------------------------------------------------------------
    async def save_historico(self, payload: Dict[str, Any]) -> None:
        await self._insert("historico_produccion", payload)

    async def save_alerta(self, payload: Dict[str, Any]) -> None:
        limpio = {
            "linea_id": payload.get("linea_id"),
            "maquina_id": payload.get("maquina_id"),
            "maquina_nombre": payload.get("maquina_nombre"),
            "severidad": payload.get("severidad", "info"),
            "tipo_alerta": payload.get("tipo_alerta", "evento"),
            "mensaje": payload.get("mensaje", ""),
            "temperatura": payload.get("temperatura"),
            "salud": payload.get("salud"),
            "resuelta": bool(payload.get("resuelta", False)),
        }
        await self._insert("alertas_maquinaria", limpio)

    async def save_comando(self, payload: Dict[str, Any]) -> None:
        await self._insert("comandos_control", payload)
