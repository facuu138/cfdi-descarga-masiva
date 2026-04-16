"""Punto de entrada CLI para la descarga masiva de CFDI del SAT."""
import csv
import json
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()


@click.group()
def cli():
    """Herramienta de descarga masiva de CFDI del SAT."""
    pass


@cli.command()
@click.option("--rfc", default=lambda: os.environ.get("SAT_RFC"), required=True, help="RFC del contribuyente (default: SAT_RFC en .env)")
@click.option("--fecha-inicio", required=True, help="Fecha inicial (YYYY-MM-DD)")
@click.option("--fecha-fin", required=True, help="Fecha final (YYYY-MM-DD)")
@click.option(
    "--tipo",
    type=click.Choice(["emitidas", "recibidas", "ambas"]),
    default="ambas",
    help="Tipo de comprobantes a descargar",
)
@click.option(
    "--formato",
    type=click.Choice(["xml", "json", "csv"]),
    default="xml",
    help="Formato de salida (xml=solo XMLs en disco, json=parsed JSON, csv=parsed CSV)",
)
@click.option("--directorio-salida", default="descargas", help="Carpeta de salida")
@click.option("--dry-run", is_flag=True, help="Simula sin descargar paquetes")
def descargar(rfc, fecha_inicio, fecha_fin, tipo, formato, directorio_salida, dry_run):
    """Descarga CFDIs del SAT y los guarda en disco."""
    from sat_cfdi.auth.cliente import ClienteAutenticacion
    from sat_cfdi.solicitud import ClienteSolicitud
    from sat_cfdi.verificacion import VerificadorSolicitud

    cert_path = os.environ.get("SAT_CERT_PATH")
    key_path = os.environ.get("SAT_KEY_PATH")
    key_password = os.environ.get("SAT_KEY_PASSWORD")

    if not cert_path:
        cert_path = click.prompt("Ruta al archivo .cer")
    if not key_path:
        key_path = click.prompt("Ruta al archivo .key")
    if not key_password:
        key_password = click.prompt("Contraseña del .key", hide_input=True)

    click.echo(f"Iniciando descarga para RFC: {rfc}")
    click.echo(f"Periodo: {fecha_inicio} → {fecha_fin}")
    click.echo(f"Tipo: {tipo} | Formato: {formato}")
    if dry_run:
        click.echo("Modo simulación activo — no se descargarán paquetes")

    click.echo("\nAutenticando con SAT...")
    try:
        cliente_auth = ClienteAutenticacion(cert_path, key_path, key_password)
        token = cliente_auth.autenticar()
        click.echo("✓ Autenticación exitosa")
    except Exception as e:
        click.echo(f"✗ Error en autenticación: {e}", err=True)
        sys.exit(1)

    if tipo == "emitidas":
        solicitudes = [("emitidas",)]
    elif tipo == "recibidas":
        solicitudes = [("recibidas",)]
    else:
        solicitudes = [("emitidas",), ("recibidas",)]

    for (tipo_label,) in solicitudes:
        click.echo(f"\nSolicitando descarga {tipo_label}...")

        try:
            token = cliente_auth.autenticar()
        except Exception as e:
            click.echo(f"✗ Error re-autenticando para {tipo_label}: {e}", err=True)
            sys.exit(1)

        try:
            cliente_sol = ClienteSolicitud(cliente_auth.certificado, token)
            if tipo_label == "emitidas":
                id_solicitud = cliente_sol.solicitar_emitidas(
                    fecha_inicial=fecha_inicio,
                    fecha_final=fecha_fin,
                    rfc_emisor=rfc,
                )
            else:
                id_solicitud = cliente_sol.solicitar_recibidas(
                    fecha_inicial=fecha_inicio,
                    fecha_final=fecha_fin,
                    rfc_receptor=rfc,
                )
        except Exception as e:
            click.echo(f"✗ Error solicitando descarga {tipo_label}: {e}", err=True)
            sys.exit(1)

        click.echo(f"✓ Solicitud aceptada. ID: {id_solicitud}")
        click.echo("Verificando estado (puede tardar varios minutos)...")

        try:
            verificador = VerificadorSolicitud(cliente_auth.certificado, token)
            resultado = verificador.verificar(id_solicitud, rfc)
        except Exception as e:
            click.echo(f"✗ Error en verificación {tipo_label}: {e}", err=True)
            continue

        num_cfdis = resultado.get("num_cfdis", 0)
        ids_paquetes = resultado.get("ids_paquetes", [])
        click.echo(
            f"✓ Descarga lista — CFDIs: {num_cfdis}, paquetes: {len(ids_paquetes)}"
        )

        if dry_run:
            click.echo("Modo simulación — paquetes disponibles:")
            for pkg in ids_paquetes:
                click.echo(f"  → {pkg}")
            continue

        from sat_cfdi.descarga import ClienteDescarga

        cliente_descarga = ClienteDescarga(
            certificado=cliente_auth.certificado,
            token_wrap=token,
            directorio_salida=directorio_salida,
        )

        todos_xmls = []
        for i, id_paquete in enumerate(ids_paquetes, 1):
            click.echo(f"  Descargando paquete {i}/{len(ids_paquetes)}: {id_paquete}...")
            try:
                rutas = cliente_descarga.descargar_paquete(id_paquete, rfc)
                todos_xmls.extend(rutas)
                click.echo(f"  ✓ {len(rutas)} XMLs extraídos → {directorio_salida}/{id_paquete}/")
            except Exception as e:
                click.echo(f"  ✗ Error en paquete {id_paquete}: {e}", err=True)
                continue

        if formato == "xml":
            click.echo(f"\n✓ {len(todos_xmls)} XMLs guardados en {directorio_salida}/")

        elif formato in ("json", "csv"):
            _exportar(todos_xmls, tipo_label, rfc, fecha_inicio, fecha_fin, formato, directorio_salida)


def _exportar(rutas_xml, tipo_label, rfc, fecha_inicio, fecha_fin, formato, directorio_salida):
    """Parsea XMLs y exporta a JSON o CSV."""
    from sat_cfdi.parser import parsear_cfdi

    tipo_corto = tipo_label[:-1]  # emitidas→emitida
    cfdis_datos = []
    fallidos = []

    click.echo(f"\nParsando {len(rutas_xml)} XMLs...")
    for ruta in rutas_xml:
        try:
            with open(ruta, "rb") as f:
                cfdi = parsear_cfdi(f.read())
            cfdis_datos.append((cfdi, tipo_corto))
        except Exception as e:
            fallidos.append(f"{ruta}: {e}")

    if fallidos:
        for err in fallidos:
            click.echo(f"  ✗ {err}", err=True)

    if not cfdis_datos:
        click.echo("Sin CFDIs parseados.")
        return

    nombre_base = f"cfdis_{tipo_label}_{rfc}_{fecha_inicio}_{fecha_fin}"
    carpeta = Path(directorio_salida)

    if formato == "json":
        ruta_salida = carpeta / f"{nombre_base}.json"
        registros = []
        for cfdi, tipo in cfdis_datos:
            datos = cfdi.model_dump(mode="json")
            datos["tipo"] = tipo
            # xml_raw puede ser muy grande — excluir por defecto
            datos.pop("xml_raw", None)
            registros.append(datos)

        with open(ruta_salida, "w", encoding="utf-8") as f:
            json.dump(registros, f, ensure_ascii=False, indent=2, default=str)

        click.echo(f"✓ {len(registros)} CFDIs exportados → {ruta_salida}")

    elif formato == "csv":
        ruta_salida = carpeta / f"{nombre_base}.csv"
        campos = [
            "uuid", "tipo", "fecha", "fecha_timbrado", "tipo_comprobante",
            "serie", "folio",
            "rfc_emisor", "nombre_emisor", "regimen_fiscal_emisor",
            "rfc_receptor", "nombre_receptor", "regimen_fiscal_receptor", "uso_cfdi",
            "moneda", "tipo_cambio", "subtotal", "descuento", "total",
            "total_iva_trasladado", "total_iva_retenido",
            "total_isr_retenido", "total_ieps_trasladado",
            "forma_pago", "metodo_pago", "lugar_expedicion", "exportacion",
        ]

        with open(ruta_salida, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
            writer.writeheader()
            for cfdi, tipo in cfdis_datos:
                datos = cfdi.model_dump(mode="json")
                datos["tipo"] = tipo
                datos.pop("xml_raw", None)
                datos.pop("conceptos", None)
                writer.writerow(datos)

        click.echo(f"✓ {len(cfdis_datos)} CFDIs exportados → {ruta_salida}")


@cli.command()
@click.argument("archivo_xml")
def parsear(archivo_xml):
    """Parsea un XML de CFDI y muestra sus campos principales."""
    from sat_cfdi.parser import parsear_cfdi_archivo
    import json

    try:
        cfdi = parsear_cfdi_archivo(archivo_xml)
    except Exception as e:
        click.echo(f"✗ Error parseando: {e}", err=True)
        sys.exit(1)

    datos = cfdi.model_dump(mode="json")
    datos.pop("xml_raw", None)
    datos.pop("conceptos", None)

    click.echo(json.dumps(datos, ensure_ascii=False, indent=2, default=str))
    click.echo(f"\nConceptos: {len(cfdi.conceptos)}")
    for i, c in enumerate(cfdi.conceptos, 1):
        click.echo(f"  {i}. {c.descripcion} — ${c.importe:,.2f}")
