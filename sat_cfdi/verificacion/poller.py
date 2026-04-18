"""Verificador de estado de solicitudes SolicitaDescarga."""
import time
import typing
import click
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

    TOKEN_TTL_SEGUNDOS = 5 * 60   # TTL real del token SAT
    TOKEN_MARGEN_SEGUNDOS = 60    # refrescar con 1 min de margen antes de expirar

    def __init__(
        self,
        certificado: CertificadoEfirma,
        token_wrap: str,
        cliente_autenticacion=None,
        token_obtenido_en: typing.Optional[float] = None,
    ):
        """
        Inicializa verificador con credenciales.

        Args:
            certificado: CertificadoEfirma cargado
            token_wrap: Token WRAP de Autenticacion
            cliente_autenticacion: ClienteAutenticacion opcional para refrescar token
                                   automáticamente cuando esté próximo a expirar
            token_obtenido_en: time.monotonic() del momento en que se obtuvo el token.
                               Si no se provee, se usa el momento de construcción del objeto
                               (puede subestimar el tiempo transcurrido).
        """
        super().__init__(certificado)
        self.token_wrap = token_wrap
        self._cliente_auth = cliente_autenticacion
        self._token_obtenido_en = token_obtenido_en if token_obtenido_en is not None else time.monotonic()

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

            # estado 0 = SAT aún no asignó estado (en cola), tratar como en proceso

            estado_str = self.ESTADOS.get(estado, f"?({estado})")
            click.echo(
                f"  [{intento}/{max_intentos}] Estado: {estado_str} "
                f"— esperando {intervalo_segundos}s..."
            )
            time.sleep(intervalo_segundos)

        raise Exception(f"Timeout verificando solicitud {id_solicitud}")

    def _refrescar_token_si_necesario(self) -> None:
        """Refresca el token solo cuando está próximo a expirar.

        Si la re-autenticación falla, loguea un warning y continúa con
        el token existente (puede aún ser válido).
        """
        if self._cliente_auth is None:
            return
        elapsed = time.monotonic() - self._token_obtenido_en
        if elapsed < self.TOKEN_TTL_SEGUNDOS - self.TOKEN_MARGEN_SEGUNDOS:
            return  # token aún vigente
        try:
            self.token_wrap = self._cliente_auth.autenticar()
            self._token_obtenido_en = time.monotonic()
        except Exception as e:
            click.echo(
                f"  [warn] No se pudo refrescar token ({e}); "
                "continuando con token actual.",
                err=True,
            )

    def _verificar_una_vez(self, id_solicitud: str, rfc_solicitante: str) -> dict:
        """Realiza una verificación (no espera, solo una llamada)."""
        self._refrescar_token_si_necesario()
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
            resultado = self._extraer_resultado(respuesta.text)
            if resultado.get("estado", -1) == 0:
                click.echo(f"  [DEBUG RAW] {respuesta.text[:2000]}")
            return resultado
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

            estado_raw = result.get("EstadoSolicitud", "")
            try:
                estado = int(estado_raw)
            except (ValueError, TypeError):
                click.echo(f"  [DEBUG] EstadoSolicitud inesperado: {estado_raw!r}")
                click.echo(f"  [DEBUG] Atributos result: {dict(result.attrib)}")
                estado = 4
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
