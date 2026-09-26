"""
backend/utilidades/simulator.py
============
Motor de simulación del gemelo digital de una línea de producción industrial.

Modela 5 estaciones en serie (extrusora, inyectora, prensa, horno, empacadora)
con degradación de salud, eventos aleatorios, consumo energético y costos
operativos en USD. Expone KPIs de negocio (OEE, cuello de botella, costo
unitario) alineados a la lógica de consultoría estratégica de Venezuela Insights.
"""

import random
from collections import deque
from datetime import datetime, timezone

# --- Parámetros económicos de referencia (contexto Venezuela, USD) ------------
TARIFA_KWH_USD = 0.12            # tarifa industrial de referencia USD/kWh
COSTO_MINUTO_PARADA_USD = 42.0   # costo de oportunidad por minuto de línea caída

ESTADOS_VALIDOS = ("operando", "mantenimiento", "alerta", "parada")


# ==============================================================================
#  MÁQUINA
# ==============================================================================
class Machine:
    """Una estación individual de la línea de producción."""

    def __init__(self, mid: str, nombre: str, temp_base: float,
                 kw_base: float, upm_base: float):
        self.id = mid
        self.nombre = nombre
        self.temp_base = float(temp_base)      # temperatura nominal °C
        self.kw_base = float(kw_base)          # potencia nominal kW
        self.upm_base = float(upm_base)        # unidades/minuto nominales

        self.estado = "operando"
        self.temperatura = self.temp_base
        self.consumo_kw = self.kw_base
        self.upm = self.upm_base
        self.salud = round(random.uniform(88.0, 99.0), 2)
        self.vibracion = 0.25
        self.tiempo_estado = 0
        self.unidades_acumuladas = 0.0

    # --------------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "estado": self.estado,
            "temperatura": round(self.temperatura, 2),
            "consumo_kw": round(self.consumo_kw, 2),
            "upm": round(self.upm, 2),
            "salud": round(self.salud, 2),
            "vibracion": round(self.vibracion, 3),
            "unidades_acumuladas": round(self.unidades_acumuladas, 1),
            "temperatura_base": self.temp_base,
        }

    # --------------------------------------------------------------------------
    def set_estado(self, nuevo: str, motivo: str = "") -> dict:
        """Cambia el estado de la máquina y devuelve el evento generado."""
        anterior = self.estado
        self.estado = nuevo
        self.tiempo_estado = 0

        if nuevo == "alerta":
            self.temperatura = max(self.temperatura, self.temp_base * 1.15)
            self.vibracion = max(self.vibracion, 4.0)
            self.upm = 0.0
        elif nuevo == "parada":
            self.upm = 0.0

        if nuevo == "alerta":
            severidad = "critical"
        elif nuevo in ("parada", "mantenimiento"):
            severidad = "warning"
        else:
            severidad = "info"

        return {
            "maquina_id": self.id,
            "maquina_nombre": self.nombre,
            "severidad": severidad,
            "tipo_alerta": f"cambio_estado_{nuevo}",
            "mensaje": f"{self.nombre}: {anterior} → {nuevo}. {motivo}".strip(),
            "temperatura": round(self.temperatura, 2),
            "salud": round(self.salud, 2),
            "resuelta": nuevo in ("operando",),
        }

    # --------------------------------------------------------------------------
    def tick(self) -> list:
        """Avanza un segundo de simulación. Devuelve la lista de eventos."""
        eventos = []
        self.tiempo_estado += 1

        # ---- PARADA (emergencia, no produce, se enfría) ----------------------
        if self.estado == "parada":
            self.temperatura = max(24.0, self.temperatura - 1.8)
            self.consumo_kw = max(0.0, self.consumo_kw * 0.55)
            self.upm = 0.0
            self.vibracion = 0.0
            return eventos

        # ---- MANTENIMIENTO (recupera salud, sin producción) ------------------
        if self.estado == "mantenimiento":
            self.salud = min(100.0, self.salud + random.uniform(1.6, 3.2))
            self.temperatura += (self.temp_base * 0.30 - self.temperatura) * 0.20
            self.consumo_kw += (self.kw_base * 0.30 - self.consumo_kw) * 0.25
            self.upm = 0.0
            self.vibracion = round(random.uniform(0.02, 0.12), 3)
            if self.salud >= 97.5 and self.tiempo_estado >= 6:
                eventos.append(self.set_estado("operando", "Mantenimiento completado"))
            return eventos

        # ---- ALERTA (falla activa, requiere intervención) --------------------
        if self.estado == "alerta":
            self.temperatura = min(self.temp_base * 1.70,
                                   self.temperatura + random.uniform(0.4, 1.7))
            self.vibracion = round(min(9.9, self.vibracion + random.uniform(0.1, 0.5)), 2)
            self.consumo_kw = max(0.0, self.kw_base * random.uniform(0.15, 0.55))
            self.upm = max(0.0, self.upm_base * random.uniform(0.0, 0.12))
            self.salud = max(0.0, self.salud - random.uniform(0.05, 0.35))
            # Auto-recuperación de emergencia si nadie interviene en 25 s
            if self.tiempo_estado > 25:
                eventos.append(self.set_estado("mantenimiento", "Auto-recuperación de emergencia"))
            return eventos

        # ---- OPERANDO (régimen normal) --------------------------------------
        self.salud = max(0.0, self.salud - random.uniform(0.02, 0.20))
        self.temperatura += (self.temp_base - self.temperatura) * 0.25 + random.uniform(-0.7, 0.7)
        self.consumo_kw = max(0.5, self.kw_base * random.uniform(0.90, 1.12))

        factor_salud = 0.60 + 0.40 * (self.salud / 100.0)
        self.upm = max(0.0, self.upm_base * factor_salud * random.uniform(0.94, 1.06))
        self.vibracion = round(
            max(0.05, (1 - self.salud / 100.0) * 3.0 + random.uniform(0.05, 0.30)), 3
        )

        # Eventos aleatorios
        if self.salud < 30.0 and random.random() < 0.060:
            eventos.append(self.set_estado("alerta", "Degradación crítica de componente"))
        elif self.temperatura > self.temp_base * 1.25 and random.random() < 0.050:
            eventos.append(self.set_estado("alerta", "Sobrecalentamiento detectado"))
        elif random.random() < 0.0035:
            eventos.append(self.set_estado("mantenimiento", "Mantenimiento preventivo programado"))

        return eventos


# ==============================================================================
#  LÍNEA DE PRODUCCIÓN
# ==============================================================================
class ProductionLine:
    """Línea en serie: el throughput queda limitado por la estación más lenta."""

    def __init__(self, linea_id: str = "LINEA-01"):
        self.linea_id = linea_id
        self.machines = [
            Machine("M1", "Extrusora",         185.0, 12.5, 48.0),
            Machine("M2", "Inyectora",         210.0, 18.0, 45.0),
            Machine("M3", "Prensa Hidráulica",  95.0, 22.0, 42.0),
            Machine("M4", "Horno de Curado",   240.0, 30.0, 44.0),
            Machine("M5", "Empacadora",         45.0,  8.0, 60.0),
        ]
        self.upm_nominal = min(m.upm_base for m in self.machines)  # 42 UPM

        self.unidades_totales = 0.0
        self.unidades_defectuosas = 0.0
        self.energia_acumulada_kwh = 0.0
        self.costo_energia_acumulado = 0.0
        self.estado_linea = "operando"

        self.arranque = datetime.now(timezone.utc)
        self.ticks = 0
        self.ticks_operando = 0

        self.alertas_recientes = deque(maxlen=15)
        self._pendientes_db = []      # eventos aún no persistidos en Supabase

    # --------------------------------------------------------------------------
    #  UTILIDADES
    # --------------------------------------------------------------------------
    def _get(self, mid: str):
        return next((m for m in self.machines if m.id == mid), None)

    def _registrar(self, eventos: list) -> list:
        """Sella los eventos con timestamp y los encola para la UI y Supabase."""
        ahora = datetime.now(timezone.utc).isoformat()
        for ev in eventos:
            ev["timestamp"] = ahora
            ev["linea_id"] = self.linea_id
            self.alertas_recientes.appendleft(ev)
            self._pendientes_db.append(ev)
        return eventos

    def pop_pendientes(self) -> list:
        """Devuelve y vacía la cola de eventos pendientes de persistir."""
        pendientes, self._pendientes_db = self._pendientes_db, []
        return pendientes

    # --------------------------------------------------------------------------
    #  MÉTRICAS
    # --------------------------------------------------------------------------
    def _metricas(self) -> dict:
        operando = [m for m in self.machines if m.estado == "operando"]

        # La línea es serie: el throughput lo fija la estación más lenta activa.
        upm_linea = min((m.upm for m in operando), default=0.0)

        consumo_kw = sum(m.consumo_kw for m in self.machines)
        temp_prom = sum(m.temperatura for m in self.machines) / len(self.machines)

        disponibilidad = (self.ticks_operando / self.ticks * 100.0) if self.ticks else 0.0
        rendimiento = min((upm_linea / self.upm_nominal * 100.0) if self.upm_nominal else 0.0, 100.0)
        calidad = ((1 - self.unidades_defectuosas / self.unidades_totales) * 100.0) \
            if self.unidades_totales > 1 else 100.0
        oee = disponibilidad * rendimiento * calidad / 10000.0

        costo_energia_hora = consumo_kw * TARIFA_KWH_USD
        costo_paradas_hora = 0.0 if upm_linea > 0 else COSTO_MINUTO_PARADA_USD * 60.0
        costo_operativo_hora = costo_energia_hora + costo_paradas_hora

        unidades_hora = upm_linea * 60.0
        costo_unitario = (costo_energia_hora / unidades_hora) if unidades_hora > 0 else 0.0

        return {
            "upm": upm_linea,
            "unidades_hora": unidades_hora,
            "consumo_kw": consumo_kw,
            "temperatura_promedio": temp_prom,
            "disponibilidad": disponibilidad,
            "rendimiento": rendimiento,
            "calidad": calidad,
            "oee": oee,
            "costo_energia_hora": costo_energia_hora,
            "costo_paradas_hora": costo_paradas_hora,
            "costo_operativo_hora": costo_operativo_hora,
            "costo_unitario_usd": costo_unitario,
        }

    # --------------------------------------------------------------------------
    def insights(self) -> list:
        """Genera los 'insights de negocio' que muestran el valor del gemelo."""
        m = self._metricas()
        salida = []

        # 1. Cuello de botella dinámico
        activas = [x for x in self.machines if x.estado == "operando"]
        if activas:
            cuello = min(activas, key=lambda x: x.upm)
            mejora = cuello.upm * 0.10
            salida.append({
                "tipo": "cuello_botella",
                "titulo": f"Cuello de botella: {cuello.nombre}",
                "detalle": (f"Limita la línea a {cuello.upm:.1f} UPM. "
                            f"Un +10% en esta estación elevaría la salida a {cuello.upm + mejora:.1f} UPM "
                            f"(≈ {mejora * 60 * 24:.0f} unidades/día adicionales)."),
            })
        else:
            salida.append({
                "tipo": "parada",
                "titulo": "Línea detenida",
                "detalle": (f"Pérdida de oportunidad estimada: "
                            f"${COSTO_MINUTO_PARADA_USD:.2f}/minuto "
                            f"(${COSTO_MINUTO_PARADA_USD * 60:.2f}/hora)."),
            })

        # 2. Costo energético unitario
        salida.append({
            "tipo": "costo",
            "titulo": f"Costo energético unitario: ${m['costo_unitario_usd']:.4f}/ud",
            "detalle": (f"Tarifa de referencia ${TARIFA_KWH_USD:.2f}/kWh. "
                        f"Consumo instantáneo {m['consumo_kw']:.1f} kW "
                        f"→ ${m['costo_energia_hora']:.2f}/hora."),
        })

        # 3. Proyección mensual de OPEX energético
        horas_transcurridas = max(self.ticks / 3600.0, 1.0 / 3600.0)
        costo_hora_prom = self.costo_energia_acumulado / horas_transcurridas
        salida.append({
            "tipo": "proyeccion",
            "titulo": f"Proyección OPEX energético: ${costo_hora_prom * 24 * 30:,.2f}/mes",
            "detalle": (f"Basado en {horas_transcurridas * 60:.1f} min de operación. "
                        f"Ahorro estimado con -5% de consumo: "
                        f"${costo_hora_prom * 24 * 30 * 0.05:,.2f}/mes."),
        })

        return salida

    # --------------------------------------------------------------------------
    #  PAYLOADS
    # --------------------------------------------------------------------------
    def snapshot(self) -> dict:
        m = self._metricas()
        return {
            "type": "telemetry",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "linea": {
                "id": self.linea_id,
                "estado": self.estado_linea,
                "upm": round(m["upm"], 2),
                "unidades_hora": round(m["unidades_hora"], 1),
                "unidades_totales": int(self.unidades_totales),
                "unidades_defectuosas": int(self.unidades_defectuosas),
                "oee": round(m["oee"], 2),
                "disponibilidad": round(m["disponibilidad"], 2),
                "rendimiento": round(m["rendimiento"], 2),
                "calidad": round(m["calidad"], 2),
                "temperatura_promedio": round(m["temperatura_promedio"], 2),
                "consumo_kw": round(m["consumo_kw"], 2),
                "costo_energia_hora": round(m["costo_energia_hora"], 4),
                "costo_operativo_hora": round(m["costo_operativo_hora"], 4),
                "costo_unitario_usd": round(m["costo_unitario_usd"], 5),
                "energia_acumulada_kwh": round(self.energia_acumulada_kwh, 3),
                "costo_energia_acumulado": round(self.costo_energia_acumulado, 4),
                "uptime_seg": self.ticks,
            },
            "maquinas": [x.to_dict() for x in self.machines],
            "alertas": list(self.alertas_recientes),
            "insights": self.insights(),
        }

    def historico_payload(self) -> dict:
        m = self._metricas()
        return {
            "linea_id": self.linea_id,
            "estado_linea": self.estado_linea,
            "unidades_producidas": int(self.unidades_totales),
            "unidades_defectuosas": int(self.unidades_defectuosas),
            "upm": round(m["upm"], 2),
            "oee": round(m["oee"], 2),
            "disponibilidad": round(m["disponibilidad"], 2),
            "rendimiento": round(m["rendimiento"], 2),
            "calidad": round(m["calidad"], 2),
            "temperatura_promedio": round(m["temperatura_promedio"], 2),
            "consumo_kw": round(m["consumo_kw"], 3),
            "costo_energia_usd": round(m["costo_energia_hora"], 4),
            "costo_operativo_usd": round(m["costo_operativo_hora"], 4),
        }

    # --------------------------------------------------------------------------
    #  CONTROL (comunicación bidireccional del gemelo)
    # --------------------------------------------------------------------------
    def detener_linea(self, motivo: str = "Parada de emergencia") -> list:
        eventos = []
        for m in self.machines:
            if m.estado != "parada":
                eventos.append(m.set_estado("parada", motivo))
        self.estado_linea = "detenida"
        return self._registrar(eventos)

    def reiniciar_linea(self, motivo: str = "Reinicio manual de línea") -> list:
        eventos = []
        for m in self.machines:
            m.salud = 100.0
            eventos.append(m.set_estado("operando", motivo))
        self.estado_linea = "operando"
        return self._registrar(eventos)

    def reiniciar_maquina(self, mid: str, motivo: str = "Reinicio manual") -> list:
        m = self._get(mid)
        if not m:
            return []
        m.salud = 100.0
        return self._registrar([m.set_estado("operando", motivo)])

    def mantenimiento_maquina(self, mid: str, motivo: str = "Mantenimiento manual") -> list:
        m = self._get(mid)
        if not m:
            return []
        return self._registrar([m.set_estado("mantenimiento", motivo)])

    # --------------------------------------------------------------------------
    def tick(self) -> dict:
        """Avanza 1 segundo la simulación completa y devuelve el snapshot."""
        self.ticks += 1
        eventos = []

        for m in self.machines:
            eventos.extend(m.tick())
            m.unidades_acumuladas += m.upm / 60.0

        if eventos:
            self._registrar(eventos)

        # --- Producción y calidad ---
        m = self._metricas()
        if m["upm"] > 0:
            self.ticks_operando += 1
            self.estado_linea = "operando"
        else:
            self.estado_linea = "detenida"

        salud_prom = sum(x.salud for x in self.machines) / len(self.machines)
        tasa_defecto = 0.008 + (100.0 - salud_prom) / 100.0 * 0.060

        delta_unidades = m["upm"] / 60.0
        self.unidades_totales += delta_unidades
        self.unidades_defectuosas += delta_unidades * tasa_defecto

        # --- Energía y costos acumulados ---
        kwh_tick = m["consumo_kw"] / 3600.0
        self.energia_acumulada_kwh += kwh_tick
        self.costo_energia_acumulado += kwh_tick * TARIFA_KWH_USD

        return self.snapshot()