"""Cliente SOAP para solicitar descarga masiva de CFDI."""
import json
import requests
from pathlib import Path
from lxml import etree
from sat_cfdi.auth.certificado import CertificadoEfirma
from .constructor import ConstructorSolicitud

NS_DES = "http://DescargaMasivaTerceros.sat.gob.mx"

_CACHE_PATH = Path("descargas/.solicitudes.json")


def _cache_key(rfc: str, fecha_inicial: str, fecha_final: str, tipo: str) -> str:
    return f"{rfc}|{fecha_inicial}|{fecha_final}|{tipo}"


def _cache_load() -> dict:
    if _CACHE_PATH.exists():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def _cache_save(key: str, id_solicitud: str) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cache = _cache_load()
    cache[key] = id_solicitud
    _CACHE_PATH.write_text(json.dumps(cache, indent=2))


class ClienteSolicitud:
    """Cliente para SolicitaDescarga del SAT."""

    URL_SOLICITUD = "https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/SolicitaDescargaService.svc"

    SOAP_ACTION_EMITIDOS = "http://DescargaMasivaTerceros.sat.gob.mx/ISolicitaDescargaService/SolicitaDescargaEmitidos"
    SOAP_ACTION_RECIBIDOS = "http://DescargaMasivaTerceros.sat.gob.mx/ISolicitaDescargaService/SolicitaDescargaRecibidos"

    def __init__(self, certificado: CertificadoEfirma, token_wrap: str):
        """
        Inicializa cliente con credenciales.

        Args:
            certificado: CertificadoEfirma cargado
            token_wrap: Token WRAP obtenido de Autenticacion
        """
        self.certificado = certificado
        self.token_wrap = token_wrap
        self.constructor = ConstructorSolicitud(certificado)

    def solicitar_emitidas(
        self,
        fecha_inicial: str,
        fecha_final: str,
        rfc_emisor: str,
        tipo_solicitud: str = "CFDI",
        tipo_comprobante: str = None,
        rfc_receptores: list = None,
    ) -> str:
        """
        Solicita descarga de CFDIs emitidos.

        Args:
            fecha_inicial: YYYY-MM-DD
            fecha_final: YYYY-MM-DD
            rfc_emisor: RFC del emisor
            tipo_solicitud: CFDI | Metadata | PDF
            tipo_comprobante: I, E, P, N, T (opcional)
            rfc_receptores: Lista de RFCs receptores a filtrar (opcional)

        Returns:
            IdSolicitud
        """
        cache_key = _cache_key(rfc_emisor, fecha_inicial, fecha_final, "emitidas")
        envelope_xml = self.constructor.construir_emitidos(
            fecha_inicial=fecha_inicial,
            fecha_final=fecha_final,
            rfc_emisor=rfc_emisor,
            rfc_solicitante=rfc_emisor,
            tipo_solicitud=tipo_solicitud,
            tipo_comprobante=tipo_comprobante,
            rfc_receptores=rfc_receptores,
        )
        id_solicitud = self._post(
            envelope_xml, self.SOAP_ACTION_EMITIDOS, "SolicitaDescargaEmitidosResult",
            cache_key=cache_key,
        )
        _cache_save(cache_key, id_solicitud)
        return id_solicitud

    def solicitar_recibidas(
        self,
        fecha_inicial: str,
        fecha_final: str,
        rfc_receptor: str,
        tipo_solicitud: str = "CFDI",
        tipo_comprobante: str = None,
        rfc_emisor: str = None,
    ) -> str:
        """
        Solicita descarga de CFDIs recibidos.

        Args:
            fecha_inicial: YYYY-MM-DD
            fecha_final: YYYY-MM-DD
            rfc_receptor: RFC del receptor
            tipo_solicitud: CFDI | Metadata | PDF
            tipo_comprobante: I, E, P, N, T (opcional)
            rfc_emisor: RFC emisor para filtrar (opcional)

        Returns:
            IdSolicitud
        """
        cache_key = _cache_key(rfc_receptor, fecha_inicial, fecha_final, "recibidas")
        envelope_xml = self.constructor.construir_recibidos(
            fecha_inicial=fecha_inicial,
            fecha_final=fecha_final,
            rfc_receptor=rfc_receptor,
            rfc_solicitante=rfc_receptor,
            tipo_solicitud=tipo_solicitud,
            tipo_comprobante=tipo_comprobante,
            rfc_emisor=rfc_emisor,
        )
        id_solicitud = self._post(
            envelope_xml, self.SOAP_ACTION_RECIBIDOS, "SolicitaDescargaRecibidosResult",
            cache_key=cache_key,
        )
        _cache_save(cache_key, id_solicitud)
        return id_solicitud

    def _post(self, envelope_xml: str, soap_action: str, result_tag: str, cache_key: str = None) -> str:
        """Envía request SOAP y extrae IdSolicitud."""
        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": soap_action,
            "Authorization": f'WRAP access_token="{self.token_wrap}"',
        }

        try:
            respuesta = requests.post(
                self.URL_SOLICITUD,
                data=envelope_xml,
                headers=headers,
                verify=False,
                timeout=30,
            )
            respuesta.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"Error solicitando descarga a SAT: {e}")

        return self._extraer_id_solicitud(respuesta.text, result_tag, cache_key=cache_key)

    def _extraer_id_solicitud(self, xml_respuesta: str, result_tag: str, cache_key: str = None) -> str:
        """Extrae IdSolicitud de respuesta SOAP."""
        try:
            root = etree.fromstring(xml_respuesta.encode())
            ns = {
                "s": "http://schemas.xmlsoap.org/soap/envelope/",
                "des": NS_DES,
            }

            result = root.find(f".//des:{result_tag}", ns)
            if result is None:
                fault = root.find(".//faultstring")
                detalle = fault.text if fault is not None else xml_respuesta[:300]
                raise ValueError(f"{result_tag} no encontrado. SAT: {detalle}")

            cod_estatus = result.get("CodEstatus", "")
            mensaje = result.get("Mensaje", "")
            id_solicitud = result.get("IdSolicitud")

            # 5004 = sin datos en rango
            if cod_estatus == "5004":
                raise Exception(f"Sin datos en rango solicitado: {mensaje}")

            # 5002 = solicitud duplicada (mismos parámetros ya enviados)
            # 5005 = solicitud duplicada (variante)
            # SAT a veces devuelve el IdSolicitud original en la respuesta;
            # si no, caemos al cache local.
            if cod_estatus in ("5002", "5005"):
                if id_solicitud:
                    return id_solicitud
                if cache_key:
                    cached = _cache_load().get(cache_key)
                    if cached:
                        return cached
                raise Exception(
                    f"Solicitud duplicada (código {cod_estatus}) y no hay cache local. "
                    "Proporciona el IdSolicitud manualmente."
                )

            if cod_estatus != "5000":
                raise Exception(f"Error SAT código {cod_estatus}: {mensaje}")

            if not id_solicitud:
                raise ValueError("IdSolicitud vacío en respuesta SAT")

            return id_solicitud

        except etree.XMLSyntaxError as e:
            raise Exception(f"Error parseando respuesta SAT: {e}")
