# Guia de despliegue en Render

Esta guia configura el backend FastAPI del Gemelo Digital Industrial como un **Web Service** en Render. El dashboard/frontend se despliega en otra instancia, por ejemplo Firebase Hosting, y consume este backend mediante HTTP y WebSocket.

## 1. Requisitos previos

Antes de crear el servicio en Render, confirma lo siguiente:

- El codigo esta en un repositorio de GitHub.
- El repositorio contiene `main.py`, `requirements.txt`, `utilidades/`, `.gitignore` y `.env.example`.
- `.env` no esta incluido en GitHub.
- El proyecto de Supabase y sus tablas estan preparados si se requiere persistencia.
- Conoces el dominio publico del dashboard para configurar CORS.

## 2. Crear el Web Service

1. Entra en [Render](https://render.com/) e inicia sesion.
2. Selecciona **New > Web Service**.
3. Conecta tu cuenta de GitHub si aun no esta conectada.
4. Selecciona el repositorio del backend.
5. Si Render pregunta por el tipo de servicio, elige **Web Service**, no Static Site ni Background Worker.
6. Configura los campos siguientes:

| Campo | Valor recomendado |
| --- | --- |
| Name | `gemelo-digital-industrial-api` |
| Region | La mas cercana a tus usuarios o a Supabase |
| Branch | `main` |
| Root Directory | Vacio si el backend esta en la raiz |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/api/health` |
| Instance Type | Free para pruebas; una instancia persistente para uso continuo |

El comando de inicio debe usar exactamente `0.0.0.0` y `$PORT`. Render asigna el puerto mediante esa variable y no debe fijarse manualmente el puerto `8000` en produccion.

## 3. Version de Python

Usa una version compatible con las dependencias del proyecto. Como configuracion explicita, añade en **Environment > Environment Variables**:

```env
PYTHON_VERSION=3.11.9
```

Si tu cuenta o region de Render no ofrece esa version exacta, selecciona una version 3.10+ disponible y compatible con `requirements.txt`. No uses una version de Python distinta en desarrollo y produccion sin probar antes la instalacion.

## 4. Variables de entorno

En el servicio de Render, abre **Environment > Environment Variables** y añade:

```env
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_KEY=TU_CLAVE_DE_SUPABASE
TICK_SECONDS=1.0
PERSIST_EVERY=5
ALLOWED_ORIGINS=https://TU_DASHBOARD.web.app,https://TU_DOMINIO.com
```

### Descripcion

| Variable | Obligatoria | Uso |
| --- | --- | --- |
| `SUPABASE_URL` | No | URL del proyecto Supabase. Si falta junto con la clave, se desactiva la persistencia. |
| `SUPABASE_KEY` | No | Credencial usada por el backend para insertar historicos, alertas y comandos. |
| `TICK_SECONDS` | No | Intervalo de cada ciclo de simulacion. Valor recomendado: `1.0`. |
| `PERSIST_EVERY` | No | Numero de ciclos entre escrituras de historico. Valor recomendado: `5`. |
| `ALLOWED_ORIGINS` | Si hay dashboard web | Dominios permitidos, separados por comas. |
| `PYTHON_VERSION` | Recomendable | Version de Python solicitada a Render. |

### Reglas para secretos

- No subas `.env` a GitHub.
- No escribas `SUPABASE_KEY` en el README ni en el codigo.
- No pongas la clave de Supabase en el frontend.
- Usa el panel de Render o un secret file para valores sensibles.
- Si una clave se expone, renuévala inmediatamente en Supabase.

## 5. Configurar CORS para el dashboard externo

El frontend se ejecuta en un origen diferente al backend, por lo que `ALLOWED_ORIGINS` debe contener el origen exacto del dashboard.

Ejemplo:

```env
ALLOWED_ORIGINS=https://gemelo-dashboard.web.app,https://dashboard.tu-dominio.com
```

Consideraciones importantes:

- Incluye solo el esquema y dominio, sin rutas como `/dashboard`.
- Separa varios origenes con comas y sin espacios innecesarios.
- Incluye el dominio de preview solo si realmente lo necesitas.
- En produccion evita `ALLOWED_ORIGINS=*`.
- Si el dashboard usa otro dominio o cambia de dominio, actualiza esta variable y realiza un nuevo deploy.

## 6. URLs que usara el frontend

Cuando Render termine el primer despliegue, asignara una URL parecida a:

```text
https://gemelo-digital-industrial-api.onrender.com
```

El dashboard debe usar:

| Funcion | URL de produccion |
| --- | --- |
| API base | `https://gemelo-digital-industrial-api.onrender.com` |
| Health check | `https://gemelo-digital-industrial-api.onrender.com/api/health` |
| Snapshot | `https://gemelo-digital-industrial-api.onrender.com/api/snapshot` |
| Alertas | `https://gemelo-digital-industrial-api.onrender.com/api/alertas` |
| Control | `https://gemelo-digital-industrial-api.onrender.com/api/control` |
| WebSocket | `wss://gemelo-digital-industrial-api.onrender.com/ws` |
| Swagger | `https://gemelo-digital-industrial-api.onrender.com/docs` |

Sustituye el hostname por el que Render asigne realmente o por tu dominio personalizado.

## 7. Configurar Supabase

Si necesitas persistencia:

1. Crea o selecciona el proyecto de Supabase.
2. Crea las tablas que espera `utilidades/database.py`:
   - `historico_produccion`
   - `alertas_maquinaria`
   - `comandos_control`
3. Configura `SUPABASE_URL` y `SUPABASE_KEY` en Render.
4. Guarda las variables y ejecuta un nuevo deploy.
5. Comprueba `/api/health` y verifica que `supabase_conectado` sea `true`.
6. Revisa los logs y confirma que se insertan historicos, alertas y comandos.

Sin esas variables, la aplicacion funciona en modo sin persistencia. Esto es util para una prueba del backend, pero los historicos y alertas no sobreviviran a un reinicio de la instancia.

## 8. WebSocket y disponibilidad

El endpoint WebSocket es `/ws`. En produccion el cliente debe conectarse con `wss://`, no con `ws://`.

El dashboard debe:

- Conectarse a la URL `wss://...onrender.com/ws`.
- Esperar el snapshot inicial al abrir la conexion.
- Procesar mensajes `telemetry`, `command_ack`, `command_error` y `error`.
- Deshabilitar controles mientras la conexion este cerrada.
- Reintentar la conexion con espera progresiva y un limite razonable.
- Volver a solicitar o aceptar un snapshot despues de reconectar.
- Mostrar un estado visible de desconexion al usuario.

En el plan gratuito, Render puede suspender servicios inactivos. El primer request despues de una suspension puede tardar mas y la conexion WebSocket puede cerrarse. Para telemetria continua, considera una instancia que no se suspenda y monitoriza el consumo de recursos.

## 9. Primer despliegue

1. Guarda las variables de entorno.
2. Pulsa **Create Web Service** o **Manual Deploy > Deploy latest commit**.
3. Abre la pestaña **Logs**.
4. Espera un mensaje que indique que Uvicorn esta escuchando en `0.0.0.0` y el puerto asignado.
5. Abre la URL de health check:

```text
https://TU_SERVICIO.onrender.com/api/health
```

La respuesta debe ser un JSON con, al menos, `status: "ok"`.

6. Prueba la documentacion en `/docs`.
7. Prueba `/api/snapshot`.
8. Conecta el dashboard mediante `wss://`.

## 10. Configuracion recomendada de despliegue

### Auto Deploy

Activa **Auto-Deploy: On Commit** para que Render despliegue cada cambio enviado a la rama `main`.

Antes de hacer push:

```bash
git status
git add .
git commit -m "Describe el cambio"
git push origin main
```

No subas archivos `.env`, credenciales, bases de datos locales ni carpetas de entorno virtual.

### Health check

Manten `/api/health` como ruta de comprobacion. Esta ruta no necesita autenticacion en la version actual y debe responder rapido sin ejecutar una consulta pesada a Supabase.

### Dominio personalizado

Si usas un dominio propio:

1. En Render abre **Settings > Custom Domains**.
2. Añade el dominio.
3. Configura los registros DNS indicados por Render.
4. Espera a que Render confirme el certificado TLS.
5. Actualiza la URL HTTP, la URL WebSocket y `ALLOWED_ORIGINS`.

## 11. Solucion de problemas

### El deploy falla durante `pip install`

- Revisa la version de Python configurada.
- Confirma que `requirements.txt` esta en el Root Directory configurado.
- Comprueba que todas las versiones fijadas existan y sean compatibles.
- Lee el primer error real de los logs; los mensajes posteriores pueden ser consecuencia del mismo fallo.

### Render indica que no detecta el puerto

Usa este Start Command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

No uses `127.0.0.1` ni fijes `8000` en produccion.

### El health check devuelve error

- Comprueba los logs de arranque.
- Verifica que `main:app` corresponda a `main.py` y al objeto `app`.
- Comprueba que las variables no contengan comillas innecesarias.
- Prueba `/api/health` manualmente desde la URL publica.

### El dashboard recibe errores de CORS

- Confirma el dominio exacto desde el que se sirve el dashboard.
- Actualiza `ALLOWED_ORIGINS` en Render.
- No incluyas una ruta ni una barra final en el origen.
- Ejecuta un nuevo deploy despues de guardar la variable.

### El WebSocket no conecta

- Usa `wss://` con el servicio publico HTTPS.
- Verifica que la ruta sea `/ws`.
- Confirma que el navegador no este bloqueando contenido mixto.
- Revisa los logs mientras se intenta la conexion.
- Implementa reconexion en el dashboard para cierres por suspension o reinicio.

### Supabase aparece desconectado

- Confirma que `SUPABASE_URL` y `SUPABASE_KEY` esten configuradas en Render.
- Comprueba que no haya espacios o saltos de linea en los valores.
- Verifica la clave y la URL en Supabase.
- Revisa que las tablas esperadas existan.
- Consulta `/api/health` y los logs del servicio.

## 12. Seguridad antes de produccion

El MVP actual no implementa autenticacion ni autorizacion para los comandos de control. Antes de exponerlo a usuarios reales:

- Añade autenticacion para endpoints de control y WebSocket.
- Autoriza por rol las acciones de parada, emergencia y mantenimiento.
- Valida y limita el origen del dashboard.
- Añade rate limiting y auditoria de comandos.
- No expongas credenciales de Supabase al navegador.
- Configura alertas para errores, reinicios y desconexiones.
- Revisa que la documentacion `/docs` no deba restringirse en produccion.

## 13. Lista final de comprobacion

- [ ] El repositorio de GitHub contiene el codigo y `requirements.txt`.
- [ ] `.env` no esta versionado.
- [ ] El servicio de Render es un Web Service.
- [ ] El Build Command es `pip install -r requirements.txt`.
- [ ] El Start Command usa `0.0.0.0` y `$PORT`.
- [ ] El Health Check Path es `/api/health`.
- [ ] `ALLOWED_ORIGINS` contiene el dominio real del dashboard.
- [ ] El dashboard usa HTTPS y `wss://`.
- [ ] `/api/health` responde con `status: "ok"`.
- [ ] `/api/snapshot` devuelve telemetria.
- [ ] El WebSocket entrega el snapshot inicial y mensajes posteriores.
- [ ] Supabase esta verificado si se necesita persistencia.
- [ ] Los logs de Render no muestran errores de arranque ni de persistencia.
- [ ] Autenticacion y autorizacion estan planificadas antes del uso productivo.
