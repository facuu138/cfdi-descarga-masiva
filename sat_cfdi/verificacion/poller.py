"""Verificador de estado de solicitudes SolicitaDescarga."""
import time
from lxml import etree
import requests
from sat_cfdi.auth.certificado import CertificadoEfirma
from sat_cfdi.auth.soap import EnvolventerSOAP

NS_S = "http://schemas.xmlsoap.org/soap/envelope/"
NS_DES = "http://DescargaMasivaTerceros.sat.gob.mx"


class VerificadorSolicitud(EnvolventerSOAP):
    """Verifica estado de solicitudes de descarga masiva."""

    URL_VERIFICACION = "https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/VerificaSolicitudDescargaService.svc"
    SOAP_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/IVerificaSolicitudDescargaService/VerificaSolicitudDescarga"

    ESTADOS = {
        1: "Aceptada",
        2: "EnProceso",
        3: "Terminada",
        4: "Error",
        5: "Rechazada",
        6: "Vencida",
    }

    def __init__(self, certificado: CertificadoEfirma, token_wrap: str):
        """
        Inicializa verificador con credenciales.

        Args:
            certificado: CertificadoEfirma cargado
            token_wrap: Token WRAP de Autenticacion
        """
        super().__init__(certificado)
        self.token_wrap = token_wrap

    def verificar(
        self,
        id_solicitud: str,
        rfc_solicitante: str,
        intervalo_segundos: int = 60,
        max_intentos: int = 120,
    ) -> dict:
        """
        Verifica estado de solicitud hasta que termine o falle.

        Args:
            id_solicitud: UUID de solicitud (de SolicitaDescarga)
            rfc_solicitante: RFC quien hizo solicitud
            intervalo_segundos: Espera entre intentos (default 60s)
            max_intentos: Máx intentos (default 120 = 2h)

        Returns:
            Dict con estado, num_cfdis, ids_paquetes, etc.

        Raises:
            Exception: Si falla verificación o max_intentos alcanzado
        """
        intento = 0

        while intento < max_intentos:
            intento += 1

            respuesta = self._verificar_una_vez(id_solicitud, rfc_solicitante)
            estado = respuesta.get("estado")

            if estado == 3:  # Terminada
                return respuesta

            if estado in [4, 5, 6]:
                estado_str = self.ESTADOS.get(estado, "?")
                raise Exception(
                    f"Solicitud {estado_str}: {respuesta.get('mensaje')} "
                    f"(código {respuesta.get('codigo_estado')})"
                )

            print(
                f"[{intento}/{max_intentos}] Estado: {self.ESTADOS.get(estado, '?')} "
                f"— esperando {intervalo_segundos}s..."
            )
            time.sleep(intervalo_segundos)

        raise Exception(f"Timeout verificando solicitud {id_solicitud}")

    def _verificar_una_vez(self, id_solicitud: str, rfc_solicitante: str) -> dict:
        """Realiza una verificación (no espera, solo una llamada)."""
        envelope_xml = self._construir_verificacion(id_solicitud, rfc_solicitante)

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": self.SOAP_ACTION,
            "Authorization": f'WRAP access_token="{self.token_wrap}"',
        }

        try:
            respuesta = requests.post(
                self.URL_VERIFICACION,
                data=envelope_xml,
                headers=headers,
                verify=False,
                timeout=30,
            )
            respuesta.raise_for_status()
            return self._extraer_resultado(respuesta.text)
        except requests.RequestException as e:
            raise Exception(f"Error verificando solicitud en SAT: {e}")

    def _construir_verificacion(self, id_solicitud: str, rfc_solicitante: str) -> str:
        """Construye envolvente SOAP para VerificaSolicitudDescarga."""
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
        verifica = etree.SubElement(body, f"{{{NS_DES}}}VerificaSolicitudDescarga")

        solicitud = etree.SubElement(verifica, f"{{{NS_DES}}}solicitud")
        solicitud.set("IdSolicitud", id_solicitud)
        solicitud.set("RfcSolicitante", rfc_solicitante)

        # Signature inline en solicitud
        self._firmar_solicitud(solicitud)

        return etree.tostring(envelope, encoding="unicode", pretty_print=False)

    def _extraer_resultado(self, xml_respuesta: str) -> dict:
        """Extrae resultado de VerificaSolicitudDescarga."""
        try:
            root = etree.fromstring(xml_respuesta.encode())
            ns = {
                "s": NS_S,
                "des": NS_DES,
            }

            result = root.find(".//des:VerificaSolicitudDescargaResult", ns)
            if result is None:
                fault = root.find(".//faultstring")
                detalle = fault.text if fault is not None else xml_respuesta[:300]
                raise ValueError(f"VerificaSolicitudDescargaResult no encontrado. SAT: {detalle}")

            estado = int(result.get("EstadoSolicitud", 4))
            codigo_estado = result.get("CodigoEstadoSolicitud", "")
            num_cfdis = int(result.get("NumeroCFDIs", 0))
            mensaje = result.get("Mensaje", "")
            cod_status = result.get("CodEstatus", "")

            ids_paquetes = [
                paq.text for paq in result.findall(".//des:IdsPaquetes", ns)
                if paq.text
            ]

            return {
                "estado": estado,
                "estado_str": self.ESTADOS.get(estado, "Desconocido"),
                "codigo_estado": codigo_estado,
                "num_cfdis": num_cfdis,
                "ids_paquetes": ids_paquetes,
                "mensaje": mensaje,
                "cod_status": cod_status,
            }

        except etree.XMLSyntaxError as e:
            raise Exception(f"Error parseando verificación SAT: {e}")
