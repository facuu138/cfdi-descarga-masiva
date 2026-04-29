# cfdi-descarga-masiva

> Vibecoded con [Claude](https://claude.ai) - construido en una sesión usando Claude Code como copiloto principal.

Herramienta Python para descargar facturas (CFDI) del SAT México a través del Web Service de Descarga Masiva oficial.

Implementa el flujo completo en 4 pasos:
1. **Autenticación** — WS-Security con e.firma → token WRAP
2. **SolicitaDescarga** — POST rango de fechas + RFC → IdSolicitud
3. **VerificaSolicitudDescarga** — polling hasta que la solicitud termina
4. **DescargaMasiva** — descarga paquetes ZIP, extrae XMLs

> El WS usa SOAP + WS-Security + XMLdsig con firma RSA-SHA1 sobre el timestamp. No hay SDKs oficiales del SAT en Python — esta implementación fue construida directamente desde la [documentación oficial SAT v1.2 (dic 2023)](https://www.sat.gob.mx/cs/Satellite?blobcol=urldata&blobkey=id&blobtable=MungoBlobs&blobwhere=1461173981678&ssbinary=true).

## Requisitos

- Python 3.11+
- Certificado de e.firma vigente (archivos `.cer` y `.key`)

## Instalación

```bash
git clone https://github.com/tu-usuario/cfdi-descarga-masiva.git
cd cfdi-descarga-masiva

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e .
```

## Configuración

```bash
cp .env.example .env
```

Edita `.env`:

```env
SAT_RFC=XAXX010101000
SAT_CERT_PATH=/ruta/a/tu/efirma.cer
SAT_KEY_PATH=/ruta/a/tu/efirma.key
SAT_KEY_PASSWORD=tu_contraseña
```
> **Nunca subas tu e.firma al repositorio.** El `.gitignore` ya excluye `*.cer` y `*.key`. Guarda tus archivos fuera del directorio del proyecto, por ejemplo en `~/.sat-efirma/`.

## Parámetros

| Parámetro | Obligatorio | Default | Descripción |
|-----------|-------------|---------|-------------|
| `--fecha-inicio` | Sí | — | Fecha inicial del periodo (formato `YYYY-MM-DD`) |
| `--fecha-fin` | Sí | — | Fecha final del periodo (formato `YYYY-MM-DD`) |
| `--rfc` | No | `SAT_RFC` en `.env` | RFC del contribuyente |
| `--tipo` | No | `ambas` | `emitidas`, `recibidas` o `ambas` |
| `--tipo-solicitud` | No | `CFDI` | `CFDI` (XMLs completos), `Metadata` (CSV ligero), `PDF` |
| `--formato` | No | `xml` | `xml` (solo guarda XMLs), `json` o `csv` |
| `--directorio-salida` | No | `descargas/` | Carpeta donde se guardan los archivos |
| `--dry-run` | No | — | Simula sin descargar; muestra IDs de paquetes disponibles |

## Uso rápido (ya configurado)

Si ya tienes el `.env` con tus credenciales:

```bash
cd cfdi-descarga-masiva
source .venv/bin/activate

cfdi-descarga-masiva descargar \
  --fecha-inicio 2024-01-01 \
  --fecha-fin 2024-01-31 \
  --formato csv
```

El SAT procesa las solicitudes de forma asíncrona: primero acepta la solicitud y devuelve un ID, luego la herramienta pregunta cada 60 segundos hasta que el estado cambia a "Terminada" (puede tardar entre 1 y 30 minutos según el volumen). Una vez lista, descarga los paquetes y genera el CSV en `descargas/`.

## Uso

### Descargar CFDIs

```bash
# Descargar emitidas y recibidas de enero 2026 (guarda XMLs en disco)
cfdi-descarga-masiva descargar \
  --rfc XAXX010101000 \
  --fecha-inicio 2026-01-01 \
  --fecha-fin 2026-01-31

# Solo emitidas, exportar como JSON (sin xml_raw)
cfdi-descarga-masiva descargar \
  --rfc XAXX010101000 \
  --fecha-inicio 2026-01-01 \
  --fecha-fin 2026-03-31 \
  --tipo emitidas \
  --formato json

# Solo recibidas, exportar como CSV
cfdi-descarga-masiva descargar \
  --rfc XAXX010101000 \
  --fecha-inicio 2026-01-01 \
  --fecha-fin 2026-12-31 \
  --tipo recibidas \
  --formato csv

# Simular sin descargar (ver IDs de paquetes disponibles)
cfdi-descarga-masiva descargar \
  --rfc XAXX010101000 \
  --fecha-inicio 2026-01-01 \
  --fecha-fin 2026-01-31 \
  --dry-run

# Conteo rápido con Metadata (más ligero que CFDI completo)
cfdi-descarga-masiva descargar \
  --rfc XAXX010101000 \
  --fecha-inicio 2026-04-01 \
  --fecha-fin 2026-04-30 \
  --tipo-solicitud Metadata
```

### Parsear un XML individual

```bash
cfdi-descarga-masiva parsear descargas/paquete-uuid/factura.xml
```

### Opciones de formato de salida

| Formato | Descripción |
|---------|-------------|
| `xml` (default) | Solo guarda los XMLs descargados en `descargas/<id_paquete>/` |
| `json` | Parsea cada CFDI y genera un archivo JSON por tipo/periodo |
| `csv` | Parsea cada CFDI y genera un CSV con los campos principales |

### Tipos de solicitud (`--tipo-solicitud`)

| Tipo | Descripción |
|------|-------------|
| `CFDI` (default) | XMLs completos con todos los campos, conceptos e impuestos |
| `Metadata` | CSV ligero con UUID, RFC, montos y fechas — sin conceptos ni XML raw. Útil para conteo rápido antes de la descarga completa |
| `PDF` | PDFs de las facturas |

El campo `xml_raw` (XML completo) se excluye en los formatos JSON y CSV para mantener tamaños manejables. Los XMLs originales siempre quedan en disco.

## Estructura del proyecto

```
sat_cfdi/
├── auth/
│   ├── certificado.py    — CertificadoEfirma: carga .cer + .key DER/PKCS#8
│   ├── soap.py           — EnvolventerSOAP: WS-Security + XMLdsig
│   ├── firma.py          — firma XMLdsig enveloped para solicitudes
│   └── cliente.py        — ClienteAutenticacion → token WRAP (5 min TTL)
├── solicitud/
│   ├── constructor.py    — construye SOAP firmado emitidas/recibidas
│   └── cliente.py        — ClienteSolicitud → IdSolicitud
├── verificacion/
│   └── poller.py         — VerificadorSolicitud: polling estados 1-6
├── descarga/
│   ├── constructor.py    — SOAP por paquete
│   └── cliente.py        — ClienteDescarga: POST → ZIP → XMLs en disco
├── parser/
│   └── cfdi.py           — parsear_cfdi: XML CFDI 4.0 → modelo Pydantic
├── modelos/
│   └── __init__.py       — CFDI, Concepto, enums EstadoSolicitud, etc.
└── main.py               — CLI (click)
```

## Integración con bases de datos

Esta herramienta descarga y parsea; la persistencia queda a tu criterio.

Si usas **Supabase / PostgreSQL**, el modelo `CFDI` incluye todos los campos necesarios. Ejemplo mínimo de loader:

```python
from sat_cfdi.parser import parsear_cfdi_archivo
from supabase import create_client

supabase = create_client(url, key)

cfdi = parsear_cfdi_archivo("descargas/paquete/factura.xml")
datos = cfdi.model_dump(mode="json")
datos["tipo"] = "emitida"
datos.pop("conceptos")  # manejar aparte si necesitas líneas

supabase.table("cfdis").upsert(datos, on_conflict="uuid").execute()
```

## Códigos de estado SAT

| Código | Significado |
|--------|-------------|
| 5000 | Éxito |
| 5002 | Solicitud duplicada (mismos parámetros ya enviados) |
| 5003 | Máximo de resultados excedido (dividir rango de fechas) |
| 5004 | Sin datos en el rango solicitado |
| 5005 | Solicitud duplicada (variante) |
| 5011 | Límite diario de folios descargados |

Si recibes **5003**, divide el rango de fechas en periodos más cortos (por mes o por semana).

Si recibes **5002 o 5005**, la herramienta recupera automáticamente el ID de la solicitud anterior desde el cache local (`descargas/.solicitudes.json`) y continúa con la descarga.

## Estados de solicitud

| Estado | Descripción |
|--------|-------------|
| 1 | Aceptada |
| 2 | En proceso |
| 3 | Terminada ✓ |
| 4 | Error |
| 5 | Rechazada |
| 6 | Vencida (paquetes expiran 72h después) |

## Notas técnicas

- El token WRAP tiene TTL de 5 minutos. El CLI re-autentica antes de cada solicitud.
- Los paquetes descargados contienen ZIPs con XMLs individuales por CFDI.
- Máximo ~200k CFDIs por solicitud. Con más, el SAT retorna código 5003.
- Soporta CFDI 4.0. Los CFDI de Retenciones tienen estructura diferente — actualmente el parser cubre facturas estándar.
- Los endpoints SAT usan TLS con certificados que Python no reconoce por default; se usa `verify=False` con `requests`. Esto genera el siguiente warning esperado — **no es un error**:

  ```
  InsecureRequestWarning: Unverified HTTPS request is being made to host
  'cfdidescargamasivasolicitud.clouda.sat.gob.mx'. Adding certificate
  verification is strongly advised.
  ```

  Para suprimirlo si molesta en producción:

  ```python
  import urllib3
  urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
  ```

## Licencia

MIT
