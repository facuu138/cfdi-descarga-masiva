"""Constructor de solicitudes SolicitaDescarga para SAT."""
from lxml import etree
from sat_cfdi.auth.certificado import CertificadoEfirma
from sat_cfdi.auth.soap import EnvolventerSOAP

NS_S = "http://schemas.xmlsoap.org/soap/envelope/"
NS_DES = "http://DescargaMasivaTerceros.sat.gob.mx"


def _fecha_datetime(fecha: str, fin: bool = False) -> str:
    """Convierte YYYY-MM-DD a datetime ISO (SAT requiere xs:dateTime)."""
    if "T" in fecha:
        return fecha
    return fecha + ("T23:59:59" if fin else "T00:00:00")


class ConstructorSolicitud(EnvolventerSOAP):
    """Construye y firma envolventes SOAP para SolicitaDescarga."""

    def construir_emitidos(
        self,
        fecha_inicial: str,
        fecha_final: str,
        rfc_emisor: str,
        rfc_solicitante: str,
        tipo_solicitud: str = "CFDI",
        tipo_comprobante: str = None,
        rfc_receptores: list = None,
    ) -> str:
        """
        Construye envolvente SOAP para SolicitaDescargaEmitidos.

        Args:
            fecha_inicial: YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
            fecha_final: YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
            rfc_emisor: RFC del emisor
            rfc_solicitante: RFC del solicitante (normalmente igual a emisor)
            tipo_solicitud: CFDI | Metadata | PDF (default: CFDI)
            tipo_comprobante: I, E, P, N, T (opcional)
            rfc_receptores: Lista de RFCs receptores a filtrar (opcional)

        Returns:
            XML SOAP firmado listo para POST
        """
        envelope = self._crear_envelope()
        body = etree.SubElement(envelope, f"{{{NS_S}}}Body")
        op = etree.SubElement(body, f"{{{NS_DES}}}SolicitaDescargaEmitidos")

        solicitud = etree.SubElement(op, f"{{{NS_DES}}}solicitud")
        solicitud.set("FechaInicial", _fecha_datetime(fecha_inicial))
        solicitud.set("FechaFinal", _fecha_datetime(fecha_final, fin=True))
        solicitud.set("RfcEmisor", rfc_emisor)
        solicitud.set("RfcSolicitante", rfc_solicitante)
        solicitud.set("TipoSolicitud", tipo_solicitud)
        solicitud.set("EstadoComprobante", "Vigente")

        if tipo_comprobante:
            solicitud.set("TipoComprobante", tipo_comprobante)

        # RfcReceptores (lista, hijo del solicitud)
        if rfc_receptores:
            receptores_elem = etree.SubElement(solicitud, f"{{{NS_DES}}}RfcReceptores")
            for rfc in rfc_receptores:
                rfc_elem = etree.SubElement(receptores_elem, f"{{{NS_DES}}}RfcReceptor")
                rfc_elem.text = rfc

        # Signature inline en solicitud
        self._firmar_solicitud(solicitud)

        return etree.tostring(envelope, encoding="unicode", pretty_print=False)

    def construir_recibidos(
        self,
        fecha_inicial: str,
        fecha_final: str,
        rfc_receptor: str,
        rfc_solicitante: str,
        tipo_solicitud: str = "CFDI",
        tipo_comprobante: str = None,
        rfc_emisor: str = None,
    ) -> str:
        """
        Construye envolvente SOAP para SolicitaDescargaRecibidos.

        Args:
            fecha_inicial: YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
            fecha_final: YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS
            rfc_receptor: RFC del receptor
            rfc_solicitante: RFC del solicitante (normalmente igual a receptor)
            tipo_solicitud: CFDI | Metadata | PDF (default: CFDI)
            tipo_comprobante: I, E, P, N, T (opcional)
            rfc_emisor: RFC emisor para filtrar (opcional)

        Returns:
            XML SOAP firmado listo para POST
        """
        envelope = self._crear_envelope()
        body = etree.SubElement(envelope, f"{{{NS_S}}}Body")
        op = etree.SubElement(body, f"{{{NS_DES}}}SolicitaDescargaRecibidos")

        solicitud = etree.SubElement(op, f"{{{NS_DES}}}solicitud")
        solicitud.set("FechaInicial", _fecha_datetime(fecha_inicial))
        solicitud.set("FechaFinal", _fecha_datetime(fecha_final, fin=True))
        solicitud.set("RfcReceptor", rfc_receptor)
        solicitud.set("RfcSolicitante", rfc_solicitante)
        solicitud.set("TipoSolicitud", tipo_solicitud)
        solicitud.set("EstadoComprobante", "Vigente")

        if tipo_comprobante:
            solicitud.set("TipoComprobante", tipo_comprobante)
        if rfc_emisor:
            solicitud.set("RfcEmisor", rfc_emisor)

        # Signature inline en solicitud
        self._firmar_solicitud(solicitud)

        return etree.tostring(envelope, encoding="unicode", pretty_print=False)

    def _crear_envelope(self) -> etree._Element:
        """Crea envelope SOAP mínimo (sin WS-Security header)."""
        envelope = etree.Element(
            f"{{{NS_S}}}Envelope",
            nsmap={
                "s": NS_S,
                "des": NS_DES,
                "xd": "http://www.w3.org/2000/09/xmldsig#",
            },
        )
        etree.SubElement(envelope, f"{{{NS_S}}}Header")
        return envelope
