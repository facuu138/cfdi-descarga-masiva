"""Constructor de envolvente SOAP para DescargaMasiva del SAT."""
from lxml import etree
from sat_cfdi.auth.certificado import CertificadoEfirma
from sat_cfdi.auth.soap import EnvolventerSOAP

NS_S = "http://schemas.xmlsoap.org/soap/envelope/"
NS_DES = "http://DescargaMasivaTerceros.sat.gob.mx"


class ConstructorDescarga(EnvolventerSOAP):
    """Construye y firma envolventes SOAP para DescargaMasiva."""

    def construir_descarga_paquete(
        self,
        id_paquete: str,
        rfc_solicitante: str,
    ) -> str:
        """
        Construye envolvente SOAP para descargar un paquete.

        Usa header vacío + Signature inline en peticionDescarga
        (mismo patrón que SolicitaDescarga/VerificaSolicitudDescarga).

        Args:
            id_paquete: UUID del paquete (de VerificaSolicitudDescarga)
            rfc_solicitante: RFC quien realizó la solicitud

        Returns:
            XML SOAP firmado listo para POST
        """
        envelope = etree.Element(
            f"{{{NS_S}}}Envelope",
            nsmap={
                "s": NS_S,
                "des": NS_DES,
                "xd": "http://www.w3.org/2000/09/xmldsig#",
            },
        )
        etree.SubElement(envelope, f"{{{NS_S}}}Header")

        body = etree.SubElement(envelope, f"{{{NS_S}}}Body")
        peticion_elem = etree.SubElement(
            body, f"{{{NS_DES}}}PeticionDescargaMasivaTercerosEntrada"
        )

        peticion_data = etree.SubElement(peticion_elem, f"{{{NS_DES}}}peticionDescarga")
        peticion_data.set("IdPaquete", id_paquete)
        peticion_data.set("RfcSolicitante", rfc_solicitante)

        # Signature inline en peticionDescarga
        self._firmar_solicitud(peticion_data)

        return etree.tostring(envelope, encoding="unicode", pretty_print=False)
