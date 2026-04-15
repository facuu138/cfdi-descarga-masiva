"""Parser de XML CFDI 4.0 → modelo CFDI."""
from datetime import datetime
from typing import Optional
from lxml import etree
from sat_cfdi.modelos import CFDI, ConceptoLineaItem

NS_CFDI = "http://www.sat.gob.mx/cfd/4"
NS_TFD = "http://www.sat.gob.mx/TimbreFiscalDigital"

# Códigos de impuesto SAT
IMP_IVA = "002"
IMP_ISR = "001"
IMP_IEPS = "003"


def parsear_cfdi(xml_bytes: bytes) -> CFDI:
    """
    Parsea XML de CFDI 4.0 y retorna modelo CFDI.

    Args:
        xml_bytes: Contenido del XML como bytes

    Returns:
        Instancia de CFDI con todos los campos extraídos

    Raises:
        ValueError: Si el XML no es CFDI válido o falta UUID
    """
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"XML inválido: {e}")

    ns = {"cfdi": NS_CFDI, "tfd": NS_TFD}

    # Comprobante (raíz)
    comp = root if root.tag == f"{{{NS_CFDI}}}Comprobante" else root.find(f"{{{NS_CFDI}}}Comprobante")
    if comp is None:
        raise ValueError("Elemento cfdi:Comprobante no encontrado")

    # TimbreFiscalDigital — UUID obligatorio
    tfd = root.find(".//tfd:TimbreFiscalDigital", ns)
    if tfd is None:
        raise ValueError("TimbreFiscalDigital no encontrado — CFDI sin timbrar")

    uuid = tfd.get("UUID")
    if not uuid:
        raise ValueError("UUID vacío en TimbreFiscalDigital")

    uuid = uuid.upper()
    fecha_timbrado = _parsear_fecha(tfd.get("FechaTimbrado", ""))
    rfc_prov_certif = tfd.get("RfcProvCertif")
    no_certificado_sat = tfd.get("NoCertificadoSAT")

    # Emisor
    emisor = comp.find(f"{{{NS_CFDI}}}Emisor")
    if emisor is None:
        raise ValueError("cfdi:Emisor no encontrado")

    # Receptor
    receptor = comp.find(f"{{{NS_CFDI}}}Receptor")
    if receptor is None:
        raise ValueError("cfdi:Receptor no encontrado")

    # Impuestos globales
    impuestos_global = comp.find(f"{{{NS_CFDI}}}Impuestos")
    total_iva_trasladado = None
    total_iva_retenido = None
    total_isr_retenido = None
    total_ieps_trasladado = None

    if impuestos_global is not None:
        # Traslados — agrupar por Impuesto
        for traslado in impuestos_global.findall(f".//{{{NS_CFDI}}}Traslado"):
            imp = traslado.get("Impuesto")
            importe = _float_opt(traslado.get("Importe"))
            if imp == IMP_IVA:
                total_iva_trasladado = (total_iva_trasladado or 0.0) + (importe or 0.0)
            elif imp == IMP_IEPS:
                total_ieps_trasladado = (total_ieps_trasladado or 0.0) + (importe or 0.0)

        # Retenciones — agrupar por Impuesto
        for retencion in impuestos_global.findall(f".//{{{NS_CFDI}}}Retencion"):
            imp = retencion.get("Impuesto")
            importe = _float_opt(retencion.get("Importe"))
            if imp == IMP_IVA:
                total_iva_retenido = (total_iva_retenido or 0.0) + (importe or 0.0)
            elif imp == IMP_ISR:
                total_isr_retenido = (total_isr_retenido or 0.0) + (importe or 0.0)

    # Conceptos
    conceptos = _parsear_conceptos(comp)

    # XML raw
    xml_raw = etree.tostring(root, encoding="unicode")

    return CFDI(
        uuid=uuid,
        fecha=_parsear_fecha(comp.get("Fecha", "")),
        fecha_timbrado=fecha_timbrado,
        tipo_comprobante=comp.get("TipoDeComprobante", ""),
        serie=comp.get("Serie"),
        folio=comp.get("Folio"),
        rfc_emisor=emisor.get("Rfc", ""),
        nombre_emisor=emisor.get("Nombre", ""),
        regimen_fiscal_emisor=emisor.get("RegimenFiscal", ""),
        rfc_receptor=receptor.get("Rfc", ""),
        nombre_receptor=receptor.get("Nombre", ""),
        domicilio_fiscal_receptor=receptor.get("DomicilioFiscalReceptor"),
        regimen_fiscal_receptor=receptor.get("RegimenFiscalReceptor", ""),
        uso_cfdi=receptor.get("UsoCFDI", ""),
        moneda=comp.get("Moneda", "MXN"),
        tipo_cambio=_float_opt(comp.get("TipoCambio")),
        subtotal=float(comp.get("SubTotal", 0)),
        descuento=_float_opt(comp.get("Descuento")),
        total=float(comp.get("Total", 0)),
        total_iva_trasladado=total_iva_trasladado,
        total_iva_retenido=total_iva_retenido,
        total_isr_retenido=total_isr_retenido,
        total_ieps_trasladado=total_ieps_trasladado,
        forma_pago=comp.get("FormaPago"),
        metodo_pago=comp.get("MetodoPago"),
        lugar_expedicion=comp.get("LugarExpedicion"),
        exportacion=comp.get("Exportacion"),
        no_certificado_sat=no_certificado_sat,
        rfc_prov_certif=rfc_prov_certif,
        xml_raw=xml_raw,
        conceptos=conceptos,
    )


def parsear_cfdi_archivo(ruta: str) -> CFDI:
    """
    Parsea CFDI desde archivo en disco.

    Args:
        ruta: Ruta al archivo XML

    Returns:
        Instancia de CFDI
    """
    with open(ruta, "rb") as f:
        return parsear_cfdi(f.read())


def _parsear_conceptos(comp: etree._Element) -> list[ConceptoLineaItem]:
    """Extrae conceptos (líneas) del Comprobante."""
    conceptos = []
    conceptos_elem = comp.find(f"{{{NS_CFDI}}}Conceptos")
    if conceptos_elem is None:
        return conceptos

    for concepto_elem in conceptos_elem.findall(f"{{{NS_CFDI}}}Concepto"):
        iva_trasladado = None
        iva_retenido = None
        isr_retenido = None
        ieps_trasladado = None

        impuestos_c = concepto_elem.find(f"{{{NS_CFDI}}}Impuestos")
        if impuestos_c is not None:
            for traslado in impuestos_c.findall(f".//{{{NS_CFDI}}}Traslado"):
                imp = traslado.get("Impuesto")
                importe = _float_opt(traslado.get("Importe"))
                if imp == IMP_IVA:
                    iva_trasladado = (iva_trasladado or 0.0) + (importe or 0.0)
                elif imp == IMP_IEPS:
                    ieps_trasladado = (ieps_trasladado or 0.0) + (importe or 0.0)

            for retencion in impuestos_c.findall(f".//{{{NS_CFDI}}}Retencion"):
                imp = retencion.get("Impuesto")
                importe = _float_opt(retencion.get("Importe"))
                if imp == IMP_IVA:
                    iva_retenido = (iva_retenido or 0.0) + (importe or 0.0)
                elif imp == IMP_ISR:
                    isr_retenido = (isr_retenido or 0.0) + (importe or 0.0)

        conceptos.append(ConceptoLineaItem(
            clave_prod_serv=concepto_elem.get("ClaveProdServ", ""),
            cantidad=float(concepto_elem.get("Cantidad", 0)),
            clave_unidad=concepto_elem.get("ClaveUnidad", ""),
            unidad=concepto_elem.get("Unidad"),
            descripcion=concepto_elem.get("Descripcion", ""),
            valor_unitario=float(concepto_elem.get("ValorUnitario", 0)),
            importe=float(concepto_elem.get("Importe", 0)),
            descuento=_float_opt(concepto_elem.get("Descuento")),
            objeto_imp=concepto_elem.get("ObjetoImp", ""),
            iva_trasladado=iva_trasladado,
            iva_retenido=iva_retenido,
            isr_retenido=isr_retenido,
            ieps_trasladado=ieps_trasladado,
        ))

    return conceptos


def _parsear_fecha(texto: str) -> datetime:
    """Convierte string ISO 8601 a datetime."""
    if not texto:
        raise ValueError("Fecha vacía")
    # SAT usa formato 2026-02-03T20:24:23
    return datetime.fromisoformat(texto)


def _float_opt(valor: Optional[str]) -> Optional[float]:
    """Convierte string a float, None si ausente o vacío."""
    if valor is None or valor.strip() == "":
        return None
    try:
        return float(valor)
    except ValueError:
        return None
