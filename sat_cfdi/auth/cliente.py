"""Cliente SOAP para autenticación con SAT."""
import os
import requests
from .certificado import CertificadoEfirma
from .soap import EnvolventerSOAP


class ClienteAutenticacion:
    """Cliente para obtener token WRAP de SAT."""

    # URL del servicio SAT (actualmente usando de prueba)
    # En producción obtener de SAT portal
    URL_AUTENTICACION = "https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/Autenticacion/Autenticacion.svc"

    def __init__(self, ruta_cer: str, ruta_key: str, contraseña: str):
        """
        Inicializa cliente con credenciales e.firma.

        Args:
            ruta_cer: Ruta a .cer
            ruta_key: Ruta a .key
            contraseña: Contraseña de .key
        """
        self.certificado = CertificadoEfirma(ruta_cer, ruta_key, contraseña)
        self.envolventer = EnvolventerSOAP(self.certificado)
        self.token = None

    def autenticar(self) -> str:
        """
        Solicita token WRAP a SAT.

        Returns:
            Token en formato "eyJhbG..."

        Raises:
            Exception: Si falla autenticación
        """
        envelope_xml = self.envolventer.construir_envolvente_autenticacion()

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": "http://DescargaMasivaTerceros.gob.mx/IAutenticacion/Autentica",
        }

        try:
            respuesta = requests.post(
                self.URL_AUTENTICACION,
                data=envelope_xml,
                headers=headers,
                verify=False,  # SAT usa certificados que Python no reconoce — arreglar después
                timeout=30,
            )
            respuesta.raise_for_status()

            # Parsear response y extraer token
            self.token = self._extraer_token(respuesta.text)
            return self.token

        except requests.RequestException as e:
            raise Exception(f"Error autenticando con SAT: {e}")

    def _extraer_token(self, xml_respuesta: str) -> str:
        """Extrae token de respuesta SOAP de Autenticacion SAT."""
        from lxml import etree

        try:
            root = etree.fromstring(xml_respuesta.encode())
            ns = {
                "s": "http://schemas.xmlsoap.org/soap/envelope/",
                "auth": "http://DescargaMasivaTerceros.gob.mx",
            }
            result = root.find(".//auth:AutenticaResult", ns)
            if result is None:
                raise ValueError("AutenticaResult no encontrado en respuesta SAT")
            token = result.text
            if not token or not token.strip():
                raise ValueError("Token vacío en respuesta SAT")
            return token.strip()
        except etree.XMLSyntaxError as e:
            raise Exception(f"Error parseando respuesta SAT: {e}")
        except ValueError as e:
            raise Exception(f"Error extrayendo token SAT: {e}")

    def obtener_token(self) -> str:
        """Retorna token actual (autentica si no existe)."""
        if not self.token:
            self.autenticar()
        return self.token
