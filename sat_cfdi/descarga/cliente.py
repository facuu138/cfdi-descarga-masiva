"""Cliente para DescargaMasiva del SAT — descarga paquetes ZIP de CFDI."""
import base64
import io
import typing
import zipfile
from pathlib import Path

import click
import requests
from lxml import etree

from sat_cfdi.auth.certificado import CertificadoEfirma
from .constructor import ConstructorDescarga

if typing.TYPE_CHECKING:
    from sat_cfdi.auth.cliente import ClienteAutenticacion


class ClienteDescarga:
    """Descarga paquetes de CFDI desde SAT DescargaMasiva."""

    URL_DESCARGA = "https://cfdidescargamasiva.clouda.sat.gob.mx/DescargaMasivaService.svc"
    SOAP_ACTION = "http://DescargaMasivaTerceros.sat.gob.mx/IDescargaMasivaTercerosService/Descargar"

    def __init__(
        self,
        certificado: CertificadoEfirma,
        token_wrap: str,
        directorio_salida: str = "descargas",
        cliente_autenticacion: typing.Optional["ClienteAutenticacion"] = None,
    ):
        """
        Inicializa cliente descarga.

        Args:
            certificado: CertificadoEfirma cargado
            token_wrap: Token WRAP de Autenticacion
            directorio_salida: Carpeta donde guardar XMLs descomprimidos
            cliente_autenticacion: ClienteAutenticacion opcional para re-autenticar
                                   automáticamente antes de cada descarga de paquete
        """
        if cliente_autenticacion is not None and not callable(
            getattr(cliente_autenticacion, "autenticar", None)
        ):
            raise TypeError(
                "cliente_autenticacion debe tener un método callable 'autenticar'"
            )
        self.certificado = certificado
        self.token_wrap = token_wrap
        self.directorio_salida = Path(directorio_salida)
        self.constructor = ConstructorDescarga(certificado)
        self._cliente_auth = cliente_autenticacion

    def _refrescar_token(self) -> None:
        """Re-autentica antes de cada descarga para asegurar token vigente.

        Si la re-autenticación falla por un error transitorio, registra un
        warning y continúa con el token existente (puede aún ser válido).
        Errores de programación (TypeError, AttributeError) se re-lanzan.
        """
        if self._cliente_auth is None:
            return
        try:
            self.token_wrap = self._cliente_auth.autenticar()
        except (TypeError, AttributeError):
            raise
        except Exception as e:
            click.echo(
                f"  [warn] No se pudo refrescar token antes de descarga ({e}); "
                "continuando con token actual.",
                err=True,
            )

    def descargar_paquete(self, id_paquete: str, rfc_solicitante: str) -> list[str]:
        """
        Descarga un paquete ZIP y extrae XMLs individuales a disco.

        Args:
            id_paquete: UUID del paquete
            rfc_solicitante: RFC del solicitante

        Returns:
            Lista de rutas absolutas a los XMLs extraídos

        Raises:
            Exception: Si falla descarga o extracción
        """
        self._refrescar_token()
        envelope_xml = self.constructor.construir_descarga_paquete(
            id_paquete=id_paquete,
            rfc_solicitante=rfc_solicitante,
        )

        headers = {
            "Content-Type": "text/xml;charset=UTF-8",
            "SOAPAction": self.SOAP_ACTION,
            "Authorization": f'WRAP access_token="{self.token_wrap}"',
        }

        try:
            respuesta = requests.post(
                self.URL_DESCARGA,
                data=envelope_xml,
                headers=headers,
                verify=False,
                timeout=120,  # paquetes grandes pueden tardar
            )
            respuesta.raise_for_status()
        except requests.RequestException as e:
            raise Exception(f"Error descargando paquete {id_paquete}: {e}")

        # Extraer base64 ZIP de respuesta SOAP
        import os
        if os.environ.get("SAT_DEBUG"):
            print(f"[DEBUG] Respuesta DescargaMasiva ({len(respuesta.text)} chars):\n{respuesta.text[:2000]}")
        datos_zip = self._extraer_paquete(respuesta.text, id_paquete)

        # Descomprimir y guardar XMLs
        rutas = self._descomprimir_paquete(datos_zip, id_paquete)
        return rutas

    def descargar_todos(self, ids_paquetes: list[str], rfc_solicitante: str) -> dict[str, list[str]]:
        """
        Descarga todos los paquetes de una solicitud.

        Args:
            ids_paquetes: Lista de IDs de paquetes
            rfc_solicitante: RFC del solicitante

        Returns:
            Dict {id_paquete: [rutas_xml, ...]}
        """
        resultados = {}
        for id_paquete in ids_paquetes:
            rutas = self.descargar_paquete(id_paquete, rfc_solicitante)
            resultados[id_paquete] = rutas
        return resultados

    def _extraer_paquete(self, xml_respuesta: str, id_paquete: str) -> bytes:
        """Extrae ZIP en base64 de respuesta SOAP DescargaMasiva (v1.5)."""
        try:
            root = etree.fromstring(xml_respuesta.encode())

            ns = {
                "s": "http://schemas.xmlsoap.org/soap/envelope/",
                "des": "http://DescargaMasivaTerceros.sat.gob.mx",
            }

            # v1.5: estado en Header/respuesta
            respuesta = root.find(".//des:respuesta", ns)
            if respuesta is not None:
                cod_estatus = respuesta.get("CodEstatus", "")
                mensaje = respuesta.get("Mensaje", "")
                if cod_estatus != "5000":
                    raise Exception(
                        f"Error SAT al descargar paquete {id_paquete}: "
                        f"código {cod_estatus} — {mensaje}"
                    )

            # v1.5: datos en Body/RespuestaDescargaMasivaTercerosSalida/Paquete
            paquete_elem = root.find(".//des:Paquete", ns)
            if paquete_elem is None or not paquete_elem.text:
                # Fallback: buscar en default namespace
                paquete_elem = root.find(".//{http://DescargaMasivaTerceros.sat.gob.mx}Paquete")

            if paquete_elem is None or not paquete_elem.text:
                raise ValueError(f"Elemento Paquete vacío en respuesta para {id_paquete}")

            datos_zip = base64.b64decode(paquete_elem.text.strip())
            return datos_zip

        except etree.XMLSyntaxError as e:
            raise Exception(f"Error parseando respuesta DescargaMasiva: {e}")

    def _descomprimir_paquete(self, datos_zip: bytes, id_paquete: str) -> list[str]:
        """
        Descomprime ZIP y guarda XMLs en directorio_salida/id_paquete/.

        Args:
            datos_zip: Bytes del ZIP
            id_paquete: ID del paquete (usado como subcarpeta)

        Returns:
            Lista de rutas absolutas a XMLs guardados
        """
        carpeta_paquete = self.directorio_salida / id_paquete
        carpeta_paquete.mkdir(parents=True, exist_ok=True)

        rutas_extraidas = []

        try:
            with zipfile.ZipFile(io.BytesIO(datos_zip)) as zf:
                nombres = zf.namelist()
                archivos = [n for n in nombres if not n.endswith("/")]

                if not archivos:
                    raise ValueError(
                        f"Paquete {id_paquete} está vacío"
                    )

                for nombre_archivo in archivos:
                    datos = zf.read(nombre_archivo)
                    ruta_destino = carpeta_paquete / Path(nombre_archivo).name

                    ruta_destino.write_bytes(datos)
                    rutas_extraidas.append(str(ruta_destino.resolve()))

        except zipfile.BadZipFile as e:
            raise Exception(f"Paquete {id_paquete} no es un ZIP válido: {e}")

        return rutas_extraidas
