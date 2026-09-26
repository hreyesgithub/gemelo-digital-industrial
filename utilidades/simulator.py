"""
simulator.py · v2 — Simulación de flujo discreto
=================================================
Modela el paso de unidades individuales por 5 estaciones en serie, con
buffers (WIP) entre ellas. Reproduce fenómenos reales de manufactura:
bloqueo, inanición, cuello de botella, scrap por unidad y efecto dominó.

Cada tick avanza el modelo `dt` segundos (por defecto 0.25 s).
"""

import random
from collections import deque
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
#  CONSTANTES ECONÓMICAS (contexto Venezuela, USD)
# ---------------------------------------------------------------------------
TARIFA_KWH_USD = 0.12
COSTO_MINUTO_PARADA_USD = 42.0
VENTANA_UPM_SEG = 15.0          # ventana móvil para calcular UPM real

# ---------------------------------------------------------------------------
#  ESTADOS
# ---------------------------------------------------------------------------
OPERANDO      = "operando"       # verde   · procesando normalmente
BLOQUEADA     = "bloqueada"      # naranja · buffer de salida lleno
SIN_MATERIAL  = "sin_material"   # gris    · buffer de entrada vacío
MANTENIMIENTO = "mantenimiento"  # amarillo· mantenimiento programado
ALERTA        = "alerta"         # rojo    · falla activa
PARADA        = "parada"         # apagada · emergencia


# ===========================================================================
#  MÁQUINA
# ===========================================================================
class Machine:
    """Una estación con un ciclo de procesamiento por unidad."""

    def __init__(
        self,
        mid: str,
        nombre: str,
        cycle_time: float,          # segundos por unidad (nominal)
        temp_base: float,           # °C de proceso
        kw_process: float,          # kW procesando
        kw_idle: float,             # kW en reposo
        buffer_capacity: int = 10,  # capacidad del buffer de salida
        scrap_rate_base: float = 0.005,
    ):
        self.id = mid
        self.nombre = nombre
        self.cycle_time_nominal = cycle_time
        self.cycle_time = cycle_time
        self.temp_base = temp_base
        self.kw_process = kw_process
        self.kw_idle = kw_idle
        self.buffer_capacity = buffer_capacity
        self.scrap_rate_base = scrap_rate_base

        # --- Estado de flujo ---------------------------------------------
        self.estado = SIN_MATERIAL
        self.progress = 0.0             # 0..1 dentro del ciclo actual
        self.processing = False         # ¿tiene una unidad dentro?
        self.buffer_out = 0             # unidades terminadas, esperando ser tomadas

        # --- Estado físico -----------------------------------------------
        self.temperatura = temp_base * 0.70
        self.consumo_kw = kw_idle
        self.vibracion = 0.10
        self.salud = round(random.uniform(88.0, 99.0), 2)

        # --- Métricas ----------------------------------------------------
        self.unidades_procesadas = 0
        self.unidades_scrap = 0
        self.tiempo_en_estado = 0.0
        self._eventos_unidad = deque(maxlen=200)  # (timestamp, 1) por unidad completada

    # ----------------------------------------------------------------------
    def _upm_instantaneo(self, ahora: float) -> float:
        """Unidades por minuto, medida sobre los últimos VENTANA_UPM_SEG."""
        while self._eventos_unidad and ahora - self._eventos_unidad[0] > VENTANA_UPM_SEG:
            self._eventos_unidad.popleft()
        return len(self._eventos_unidad) * 60.0 / VENTANA_UPM_SEG

    # ----------------------------------------------------------------------
    def to_dict(self, ahora: float) -> dict:
        return {
            "id": self.id,
            "nombre": self.nombre,
            "estado": self.estado,
            "progress": round(self.progress, 3),
            "processing": self.processing,
            "buffer_out": self.buffer_out,
            "buffer_capacity": self.buffer_capacity,
            "cycle_time": round(self.cycle_time, 3),
            "temperatura": round(self.temperatura, 2),
            "temperatura_base": self.temp_base,
            "consumo_kw": round(self.consumo_kw, 2),
            "salud": round(self.salud, 2),
            "vibracion": round(self.vibracion, 3),
            "unidades_procesadas": self.unidades_procesadas,
            "unidades_scrap": self.unidades_scrap,
            "upm": round(self._upm_instantaneo(ahora), 2),
        }

    # ----------------------------------------------------------------------
    def set_estado(self, nuevo: str, motivo: str = "") -> dict:
        anterior = self.estado
        self.estado = nuevo
        self.tiempo_en_estado = 0.0

        if nuevo == ALERTA:
            self.temperatura = max(self.temperatura, self.temp_base * 1.15)
            self.vibracion = max(self.vibracion, 4.0)
        if nuevo in (PARADA, ALERTA):
            self.processing = False
            self.progress = 0.0

        severidad = {
            ALERTA: "critical",
            PARADA: "warning",
            MANTENIMIENTO: "warning",
        }.get(nuevo, "info")

        return {
            "maquina_id": self.id,
            "maquina_nombre": self.nombre,
            "severidad": severidad,
            "tipo_alerta": f"cambio_estado_{nuevo}",
            "mensaje": f"{self.nombre}: {anterior} → {nuevo}. {motivo}".strip(),
            "temperatura": round(self.temperatura, 2),
            "salud": round(self.salud, 2),
            "resuelta": nuevo == OPERANDO,
        }

    # ----------------------------------------------------------------------
        # ----------------------------------------------------------------------
    def tick(self, dt: float, hay_material_entrada: bool, ahora: float) -> tuple:
        """
        Avanza un paso. Retorna (eventos, salida_unidad, consume_upstream).
          - salida_unidad    : 1 si terminó una unidad en este tick (buena o scrap)
          - consume_upstream : 1 si en este tick tomó UNA unidad del buffer del
                               upstream (para que ProductionLine la reste).
        """
        eventos = []
        self.tiempo_en_estado += dt
        consume_upstream = 0                              

        # ============ Estados no operativos ================================
        if self.estado == PARADA:
            self.processing = False
            self.progress = 0.0
            self.temperatura = max(24.0, self.temperatura - 1.8 * dt)
            self.consumo_kw = max(0.0, self.consumo_kw * (1 - 0.55 * dt))
            self.vibracion = 0.0
            return eventos, 0, 0                            

        if self.estado == MANTENIMIENTO:
            self.processing = False
            self.progress = 0.0
            self.salud = min(100.0, self.salud + random.uniform(6.0, 10.0) * dt)
            self.temperatura += (self.temp_base * 0.30 - self.temperatura) * (0.20 * dt)
            self.consumo_kw += (self.kw_idle * 0.55 - self.consumo_kw) * (0.25 * dt)
            self.vibracion = max(0.02, self.vibracion * (1 - 2.0 * dt))
            if self.salud >= 97.5 and self.tiempo_en_estado >= 5.0:
                eventos.append(self.set_estado(OPERANDO, "Mantenimiento completado"))
            return eventos, 0, 0                             

        if self.estado == ALERTA:
            self.processing = False
            self.progress = 0.0
            self.temperatura = min(self.temp_base * 1.70,
                                   self.temperatura + random.uniform(0.4, 1.7) * dt)
            self.vibracion = min(9.9, self.vibracion + random.uniform(0.2, 0.6) * dt)
            self.consumo_kw = max(self.kw_idle,
                                  self.kw_process * random.uniform(0.15, 0.40))
            self.salud = max(0.0, self.salud - random.uniform(0.3, 1.2) * dt)
            if self.tiempo_en_estado > 20.0:
                eventos.append(self.set_estado(MANTENIMIENTO,
                                               "Auto-recuperación de emergencia"))
            return eventos, 0, 0                             

        # ============ Estados productivos ==================================
        self.salud = max(0.0, self.salud - random.uniform(0.05, 0.20) * dt)

        target_temp = self.temp_base if self.processing else self.temp_base * 0.75
        self.temperatura += (target_temp - self.temperatura) * (0.40 * dt) \
                            + random.uniform(-0.6, 0.6) * dt

        target_kw = self.kw_process if self.processing else self.kw_idle
        self.consumo_kw += (target_kw - self.consumo_kw) * (0.50 * dt)
        self.consumo_kw = max(0.3, self.consumo_kw)

        base_vib = (1 - self.salud / 100.0) * 3.0
        self.vibracion = max(0.05, base_vib + random.uniform(0.05, 0.30))

        # --- ¿Tenemos una unidad dentro? ----------------------------------
        if not self.processing:
            if hay_material_entrada:
                self.processing = True
                self.progress = 0.0
                self.estado = OPERANDO
                self.tiempo_en_estado = 0.0
                consume_upstream = 1                    
            else:
                self.estado = SIN_MATERIAL
                return eventos, 0, 0                    

        # --- Avanzar el ciclo --------------------------------------------
        factor_salud = 0.85 + 0.15 * (self.salud / 100.0)
        self.cycle_time = self.cycle_time_nominal / factor_salud
        self.progress += dt / self.cycle_time

        if self.progress < 1.0:
            self.estado = OPERANDO
            return eventos, 0, consume_upstream          

        # --- Ciclo completado: ¿podemos empujar al buffer? ---------------
        if self.buffer_out >= self.buffer_capacity:
            self.progress = 1.0
            self.estado = BLOQUEADA
            return eventos, 0, consume_upstream         

        # --- Control de calidad ------------------------------------------
        scrap_rate = self.scrap_rate_base + (100 - self.salud) / 100 * 0.05
        fue_scrap = random.random() < scrap_rate

        if fue_scrap:
            self.unidades_scrap += 1
            eventos.append({
                "maquina_id": self.id,
                "maquina_nombre": self.nombre,
                "severidad": "info",
                "tipo_alerta": "scrap",
                "mensaje": f"{self.nombre}: unidad descartada por control de calidad",
                "temperatura": round(self.temperatura, 2),
                "salud": round(self.salud, 2),
                "resuelta": True,
            })
        else:
            self.buffer_out += 1
            self.unidades_procesadas += 1
            self._eventos_unidad.append(ahora)

        self.processing = False
        self.progress = 0.0

        # --- Eventos aleatorios de falla ---------------------------------
        if self.salud < 30.0 and random.random() < 0.02 * dt * 10:
            eventos.append(self.set_estado(ALERTA, "Degradación crítica de componente"))
        elif self.temperatura > self.temp_base * 1.25 and random.random() < 0.015 * dt * 10:
            eventos.append(self.set_estado(ALERTA, "Sobrecalentamiento detectado"))

        return eventos, 1, consume_upstream


# ===========================================================================
#  LÍNEA DE PRODUCCIÓN
# ===========================================================================
class ProductionLine:
    """5 estaciones en serie con buffers intermedios."""

    def __init__(self, linea_id: str = "LINEA-01"):
        self.linea_id = linea_id

        # cycle_time en segundos por unidad (nominal).
        # M3 es el cuello de botella estructural.
        self.machines = [
            Machine("M1", "Extrusora",         1.00, 185.0, 12.5, 5.0,  10),
            Machine("M2", "Inyectora",         1.15, 210.0, 18.0, 7.0,  10),
            Machine("M3", "Prensa Hidráulica", 1.40,  95.0, 22.0, 9.0,  10),
            Machine("M4", "Horno de Curado",   1.20, 240.0, 30.0, 12.0, 10),
            Machine("M5", "Empacadora",        0.85,  45.0,  8.0, 3.5,  9999),
        ]

        # UPM nominal del sistema = la estación más lenta
        self.upm_nominal = 60.0 / max(m.cycle_time_nominal for m in self.machines)

        self.estado_linea = "operando"
        self.arranque = datetime.now(timezone.utc)
        self.ticks = 0
        self.ticks_operando = 0
        self.tiempo_operando = 0.0
        self.tiempo_total = 0.0

        self.unidades_scrap_total = 0
        self.energia_acumulada_kwh = 0.0
        self.costo_energia_acumulado = 0.0

        self.alertas_recientes = deque(maxlen=15)
        self._pendientes_db = []

    # ----------------------------------------------------------------------
    def _get(self, mid: str):
        return next((m for m in self.machines if m.id == mid), None)

    def _registrar(self, eventos: list) -> list:
        ahora_iso = datetime.now(timezone.utc).isoformat()
        for ev in eventos:
            ev["timestamp"] = ahora_iso
            ev["linea_id"] = self.linea_id
            self.alertas_recientes.appendleft(ev)
            self._pendientes_db.append(ev)
        return eventos

    def pop_pendientes(self) -> list:
        pendientes, self._pendientes_db = self._pendientes_db, []
        return pendientes

    # ----------------------------------------------------------------------
    def _metricas(self) -> dict:
        # Throughput de línea: la máquina más lenta *que esté produciendo*.
        # Si alguna está bloqueada, la línea va a la velocidad del bloqueo.
        activas = [m for m in self.machines
                   if m.estado in (OPERANDO, BLOQUEADA)]
        upm_linea = 0.0
        if activas:
            # El ritmo lo fija la más lenta
            upm_linea = 60.0 / max(m.cycle_time for m in activas)

        # Si hay alerta/parada aguas arriba del cuello, la línea sigue
        # pero eventualmente se vaciará. Mostramos el "potencial".
        en_falla = [m for m in self.machines if m.estado in (ALERTA, PARADA)]
        if en_falla:
            # Si el cuello o alguna máquina aguas arriba está caída, cae a 0
            idx_falla_min = min(
                self.machines.index(m) for m in en_falla
            )
            # Si la falla está ANTES de la última estación operativa,
            # el throughput visible cae
            upm_linea = upm_linea * 0.35  # penalización realista

        consumo_kw = sum(m.consumo_kw for m in self.machines)
        temp_prom = sum(m.temperatura for m in self.machines) / len(self.machines)

        disponibilidad = (self.tiempo_operando / self.tiempo_total * 100.0) \
                         if self.tiempo_total > 0 else 0.0
        rendimiento = min(upm_linea / self.upm_nominal * 100.0, 100.0) \
                      if self.upm_nominal else 0.0

        total_procesadas = sum(m.unidades_procesadas for m in self.machines)
        total_scrap = sum(m.unidades_scrap for m in self.machines)
        calidad = 100.0 if total_procesadas + total_scrap == 0 else \
                  (total_procesadas / (total_procesadas + total_scrap) * 100.0)

        oee = disponibilidad * rendimiento * calidad / 10000.0

        costo_energia_hora = consumo_kw * TARIFA_KWH_USD
        costo_paradas_hora = 0.0 if upm_linea > 5.0 else COSTO_MINUTO_PARADA_USD * 60.0
        costo_operativo_hora = costo_energia_hora + costo_paradas_hora

        unidades_hora = upm_linea * 60.0
        costo_unitario = (costo_energia_hora / unidades_hora) if unidades_hora > 0 else 0.0

        # WIP interno (todos los buffers menos la salida final de M5)
        wip_interno = sum(m.buffer_out for m in self.machines[:-1])
        pt_acumulado = self.machines[-1].buffer_out

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
            "wip_interno": wip_interno,
            "pt_acumulado": pt_acumulado,
        }

    # ----------------------------------------------------------------------
    def insights(self) -> list:
        m = self._metricas()
        salida = []

        # --- Cuello de botella dinámico ---------------------------------
        # Es la estación con mayor acumulación upstream
        idx_cuello = 0
        max_wip = -1
        for i, maq in enumerate(self.machines[:-1]):
            if maq.buffer_out > max_wip:
                max_wip = maq.buffer_out
                idx_cuello = i + 1  # la estación que recibe este buffer

        cuello = self.machines[idx_cuello]
        if m["wip_interno"] > 0:
            mejora = 60.0 / cuello.cycle_time * 0.10
            salida.append({
                "tipo": "cuello_botella",
                "titulo": f"Cuello de botella: {cuello.nombre}",
                "detalle": (f"Con {max_wip} unidades acumuladas aguas arriba. "
                            f"Un +10% de velocidad aquí elevaría la salida "
                            f"a {60.0 / cuello.cycle_time + mejora:.1f} UPM."),
            })
        else:
            salida.append({
                "tipo": "cuello_botella",
                "titulo": f"Línea equilibrada · {m['upm']:.1f} UPM",
                "detalle": (f"Sin acumulación anómala de WIP. "
                            f"Estación limitante: {cuello.nombre} "
                            f"({60.0 / cuello.cycle_time:.1f} UPM)."),
            })

        # --- Alarma de bloqueo / inanición ------------------------------
        bloqueadas = [x for x in self.machines if x.estado == BLOQUEADA]
        inanición = [x for x in self.machines if x.estado == SIN_MATERIAL]
        if bloqueadas:
            salida.append({
                "tipo": "parada",
                "titulo": f"⚠️ {len(bloqueadas)} estación(es) bloqueada(s)",
                "detalle": (f"{', '.join(x.nombre for x in bloqueadas)} sin poder "
                            f"descargar. Algo aguas abajo es más lento. "
                            f"WIP interno total: {m['wip_interno']} uds."),
            })

        # --- Costo energético unitario ----------------------------------
        salida.append({
            "tipo": "costo",
            "titulo": f"Costo energético unitario: ${m['costo_unitario_usd']:.4f}/ud",
            "detalle": (f"Consumo instantáneo {m['consumo_kw']:.1f} kW → "
                        f"${m['costo_energia_hora']:.2f}/h a ${TARIFA_KWH_USD:.2f}/kWh."),
        })

        # --- Proyección mensual ------------------------------------------
        horas_transcurridas = max(self.tiempo_total / 3600.0, 1 / 3600.0)
        costo_hora_prom = self.costo_energia_acumulado / horas_transcurridas
        salida.append({
            "tipo": "proyeccion",
            "titulo": f"Proyección OPEX energético: ${costo_hora_prom * 24 * 30:,.2f}/mes",
            "detalle": (f"Basado en {self.tiempo_total:.0f} s de operación. "
                        f"Ahorro estimado con -5% de consumo: "
                        f"${costo_hora_prom * 24 * 30 * 0.05:,.2f}/mes."),
        })

        return salida

    # ----------------------------------------------------------------------
    def snapshot(self) -> dict:
        ahora = self.tiempo_total
        m = self._metricas()
        return {
            "type": "telemetry",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "linea": {
                "id": self.linea_id,
                "estado": self.estado_linea,
                "upm": round(m["upm"], 2),
                "upm_nominal": round(self.upm_nominal, 2),
                "unidades_hora": round(m["unidades_hora"], 1),
                "unidades_totales": int(m["pt_acumulado"]),
                "unidades_scrap": sum(x.unidades_scrap for x in self.machines),
                "wip_interno": m["wip_interno"],
                "pt_acumulado": m["pt_acumulado"],
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
                "uptime_seg": int(self.tiempo_total),
            },
            "maquinas": [x.to_dict(ahora) for x in self.machines],
            "alertas": list(self.alertas_recientes),
            "insights": self.insights(),
        }

    # ----------------------------------------------------------------------
    def historico_payload(self) -> dict:
        m = self._metricas()
        return {
            "linea_id": self.linea_id,
            "estado_linea": self.estado_linea,
            "unidades_producidas": int(m["pt_acumulado"]),
            "unidades_defectuosas": sum(x.unidades_scrap for x in self.machines),
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

    # ----------------------------------------------------------------------
    #  CONTROL
    # ----------------------------------------------------------------------
    def detener_linea(self, motivo="Parada de emergencia") -> list:
        eventos = []
        for m in self.machines:
            if m.estado != PARADA:
                eventos.append(m.set_estado(PARADA, motivo))
        self.estado_linea = "detenida"
        return self._registrar(eventos)

    def reiniciar_linea(self, motivo="Reinicio manual de línea") -> list:
        eventos = []
        for m in self.machines:
            m.salud = 100.0
            eventos.append(m.set_estado(OPERANDO, motivo))
        self.estado_linea = "operando"
        return self._registrar(eventos)

    def reiniciar_maquina(self, mid, motivo="Reinicio manual") -> list:
        m = self._get(mid)
        if not m:
            return []
        m.salud = 100.0
        return self._registrar([m.set_estado(OPERANDO, motivo)])

    def mantenimiento_maquina(self, mid, motivo="Mantenimiento manual") -> list:
        m = self._get(mid)
        if not m:
            return []
        return self._registrar([m.set_estado(MANTENIMIENTO, motivo)])

    # ----------------------------------------------------------------------
    #  TICK PRINCIPAL
    # ----------------------------------------------------------------------
    def tick(self, dt: float) -> dict:
        self.ticks += 1
        self.tiempo_total += dt

        ahora = self.tiempo_total
        eventos = []

        # --- 1 + 2. Tick de cada máquina, en orden serie, con disponibilidad
        #           recalculada ANTES de cada máquina (para que vea el efecto
        #           inmediato del completado del upstream en este mismo tick).
        for i, m in enumerate(self.machines):
            # Disponibilidad de material: el feeder (M1) siempre tiene, el
            # resto mira el buffer del upstream EN ESTE INSTANTE.
            if i == 0:
                hay_material = True
            else:
                hay_material = self.machines[i - 1].buffer_out > 0

            evs, salida_unidad, consume_upstream = m.tick(dt, hay_material, ahora)
            eventos.extend(evs)

            # --- 3. Cascada: si esta máquina tomó del upstream, restamos ---
            if consume_upstream and i > 0:
                upstream = self.machines[i - 1]
                if upstream.buffer_out > 0:
                    upstream.buffer_out -= 1

                    # Si el upstream estaba bloqueado y acabamos de liberarle
                    # espacio, despertarlo para que retome el flujo en el
                    # siguiente tick (si no está en falla ni parada).
                    if upstream.estado == BLOQUEADA and upstream.processing:
                        upstream.estado = OPERANDO

        if eventos:
            self._registrar(eventos)

        # --- 4. Métricas agregadas ---------------------------------------
        m = self._metricas()

        # --- 5. Estado global de línea -----------------------------------
        estados = [x.estado for x in self.machines]
        if PARADA in estados:
            self.estado_linea = "detenida"
        elif ALERTA in estados:
            self.estado_linea = "alerta"
        elif MANTENIMIENTO in estados:
            self.estado_linea = "mantenimiento"
        else:
            self.estado_linea = "operando"

        if m["upm"] > 5.0:
            self.ticks_operando += 1
            self.tiempo_operando += dt

        # --- 6. Energía acumulada ----------------------------------------
        kwh_tick = m["consumo_kw"] * dt / 3600.0
        self.energia_acumulada_kwh += kwh_tick
        self.costo_energia_acumulado += kwh_tick * TARIFA_KWH_USD

        return self.snapshot()
