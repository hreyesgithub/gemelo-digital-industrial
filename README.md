# Gemelo Digital Industrial

Backend de un gemelo digital para una línea de producción industrial. Simula cinco estaciones, publica telemetría en tiempo real, expone comandos de control y persiste históricos y alertas en Supabase cuando hay credenciales configuradas.

El frontend/dashboard se despliega por separado, por ejemplo en Firebase Hosting. Este repositorio contiene el backend FastAPI y el contrato que consume ese cliente externo.

## Capacidades

- Simulación continua de una línea en serie con cinco máquinas:
  - Extrusora
  - Inyectora
  - Prensa Hidráulica
  - Horno de Curado
  - Empacadora
- Telemetría por WebSocket en `/ws`.
- API REST para salud, snapshot, alertas y control.
- Estados de máquina: `operando`, `mantenimiento`, `alerta` y `parada`.
- Métricas de producción, OEE, consumo energético y costos operativos.
- Persistencia opcional en Supabase.
- Funcionamiento en modo API-only cuando no existe la carpeta `static/`.

## Requisitos

- Python 3.10 o superior.
- `pip` y un entorno virtual recomendado.
- Supabase opcional para persistencia.
- Un frontend separado puede consumir la API mediante HTTP y WebSocket.

## Instalación local

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env` con los valores de tu entorno. Nunca subas ese archivo a GitHub.

## Ejecución

```bash
uvicorn main:app --reload
```

El backend queda disponible normalmente en `http://127.0.0.1:8000`.

- Documentación Swagger: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/health`
- Snapshot actual: `http://127.0.0.1:8000/api/snapshot`
- Alertas recientes: `http://127.0.0.1:8000/api/alertas`
- WebSocket: `ws://127.0.0.1:8000/ws`

## Configuración

Variables disponibles en `.env`:

| Variable | Requerida | Valor predeterminado | Descripción |
| --- | --- | --- | --- |
| `SUPABASE_URL` | No | vacío | URL del proyecto Supabase. |
| `SUPABASE_KEY` | No | vacío | Clave de acceso usada por el backend. |
| `TICK_SECONDS` | No | `1.0` | Intervalo, en segundos, de cada ciclo de simulación. |
| `PERSIST_EVERY` | No | `5` | Cada cuántos ciclos se guarda el histórico. |
| `ALLOWED_ORIGINS` | No | `*` | Orígenes del dashboard separados por comas. |

Sin `SUPABASE_URL` y `SUPABASE_KEY`, el servicio continúa funcionando sin persistencia y registra un aviso en los logs.

Para un dashboard desplegado en otra instancia, configura por ejemplo:

```env
ALLOWED_ORIGINS=https://tu-dashboard.web.app,https://tu-dominio.com
```

Usa `https://` para la API pública y `wss://` para el WebSocket en producción. No pongas claves de Supabase en el frontend.

## API REST

### `GET /api/health`

Devuelve el estado del servicio, el número de clientes WebSocket, el estado de Supabase y los errores de persistencia.

### `GET /api/snapshot`

Devuelve el estado completo actual de la línea, sus máquinas, métricas, alertas e insights.

### `GET /api/alertas`

Devuelve las alertas recientes mantenidas por el simulador.

### `POST /api/control`

Cuerpo JSON:

```json
{
  "accion": "reiniciar_maquina",
  "maquina_id": "M2",
  "motivo": "Reinicio solicitado por el operador"
}
```

Acciones disponibles:

- `detener_linea` o `stop_line`
- `emergencia`
- `reiniciar_linea` o `start_line`
- `reiniciar_maquina` o `restart_machine`
- `mantenimiento_maquina` o `maintenance_machine`

`maquina_id` es obligatorio para reiniciar o poner en mantenimiento una máquina.

También existen los accesos rápidos:

- `POST /api/control/detener`
- `POST /api/control/reiniciar`

## WebSocket para el dashboard

Conecta el cliente externo a `/ws`.

Al conectarse recibe inmediatamente un snapshot. Después recibe mensajes de telemetría periódicos con `type: "telemetry"`.

Para enviar un comando:

```json
{
  "type": "command",
  "accion": "mantenimiento_maquina",
  "maquina_id": "M3",
  "motivo": "Mantenimiento preventivo"
}
```

Respuestas posibles:

- `command_ack`: comando ejecutado correctamente.
- `command_error`: comando inválido o con datos incompletos.
- `error`: mensaje recibido que no contiene JSON válido.

El dashboard debe contemplar snapshot inicial, reconexión, errores de red y cambios de estado antes de mostrar controles como disponibles.

## Persistencia Supabase

Cuando está habilitada, la aplicación utiliza estas tablas:

- `historico_produccion`
- `alertas_maquinaria`
- `comandos_control`

El cliente Supabase se ejecuta desde operaciones asíncronas mediante un hilo para no bloquear el bucle de simulación. El esquema de las tablas debe existir en el proyecto Supabase antes de habilitar la persistencia.

## Estructura

```text
.
├── main.py
├── requirements.txt
├── .env.example
├── utilidades/
│   ├── database.py
│   └── simulator.py
└── .github/
    └── agents/
        └── gemelo-digital-industrial.agent.md
```

La carpeta `static/` es opcional. Si existe, FastAPI la sirve como frontend estático; si no existe, el backend funciona como API-only para el dashboard externo.

## Publicar en GitHub

Desde la carpeta del proyecto:

```bash
git init
git add README.md .env.example .gitignore main.py requirements.txt utilidades .github
git status
git commit -m "Inicializa backend del gemelo digital industrial"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

Antes de `git add`, confirma que `.env`, `.venv`, `__pycache__` y otros archivos locales no aparecen en `git status`.

## Despliegue

El servicio necesita un proceso web que ejecute:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Configura las variables de entorno del proveedor de hosting en lugar de subir `.env`. Después configura en el dashboard externo:

- URL HTTP pública del backend.
- URL WebSocket pública del backend.
- Origen permitido en `ALLOWED_ORIGINS`.
- Manejo de reconexión y estado desconectado.

## Estado del proyecto

Proyecto MVP/demo orientado a telemetría, control y análisis operativo de una línea industrial simulada. Antes de usarlo en producción, añade autenticación, autorización de comandos, pruebas automatizadas, observabilidad y una política de validación de los orígenes permitidos.
