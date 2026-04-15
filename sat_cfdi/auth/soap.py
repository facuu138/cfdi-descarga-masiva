"""Constructor de envolvente SOAP con WS-Security para SAT."""
from datetime import datetime, timedelta
import base64
import uuid
from lxml import etree
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from .certificado import CertificadoEfirma

NS_XMLDSIG = "http://www.w3.org/2000/09/xmldsig#"


class EnvolventerSOAP:
    """Construye y firma envolvente SOAP con WS-Security 2004."""

    NS = {
        "s": "http://schemas.xmlsoap.org/soap/envelope/",
        "u": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd",
        "o": "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd",
        "xd": "http://www.w3.org/2000/09/xmldsig#",
    }

    def __init__(self, certificado: CertificadoEfirma):
        self.cert = certificado

    def construir_envolvente_autenticacion(self) -> str:
        """Construye envolvente SOAP para llamada a Autenticacion."""
        # Crear estructura base
        envelope = etree.Element(
            "{http://schemas.xmlsoap.org/soap/envelope/}Envelope",
            nsmap={
                "s": self.NS["s"],
                "u": self.NS["u"],
                "o": self.NS["o"],
                "xd": self.NS["xd"],
            },
        )

        # Header con Security
        header = etree.SubElement(envelope, "{http://schemas.xmlsoap.org/soap/envelope/}Header")
        security = etree.SubElement(
            header,
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}Security",
        )
        security.set("{http://schemas.xmlsoap.org/soap/envelope/}mustUnderstand", "1")

        # Timestamp
        self._agregar_timestamp(security)

        # BinarySecurityToken con certificado
        self._agregar_token_seguridad(security)

        # Signature (firma XML) — será agregada después de construir body
        # Body
        body = etree.SubElement(envelope, "{http://schemas.xmlsoap.org/soap/envelope/}Body")
        autentica = etree.SubElement(
            body, "{http://DescargaMasivaTerceros.gob.mx}Autentica"
        )

        # Firmar
        self._firmar_envolvente(envelope, security)

        return etree.tostring(envelope, encoding="unicode", pretty_print=False)

    def _agregar_timestamp(self, security_elem):
        """Agrega Timestamp a Security."""
        now = datetime.utcnow()
        expires = now + timedelta(minutes=5)

        timestamp = etree.SubElement(
            security_elem,
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Timestamp",
        )
        timestamp.set(
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Id",
            "_0",
        )

        created = etree.SubElement(
            timestamp,
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Created",
        )
        created.text = now.isoformat() + "Z"

        expires_elem = etree.SubElement(
            timestamp,
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Expires",
        )
        expires_elem.text = expires.isoformat() + "Z"

    def _agregar_token_seguridad(self, security_elem):
        """Agrega BinarySecurityToken con certificado en base64."""
        import uuid

        token = etree.SubElement(
            security_elem,
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd}BinarySecurityToken",
        )
        token_id = f"uuid-{uuid.uuid4()}-1"
        token.set(
            "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}Id",
            token_id,
        )
        token.set(
            "ValueType",
            "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3",
        )
        token.set(
            "EncodingType",
            "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary",
        )
        token.text = self.cert.obtener_cer_base64()

    def _firmar_envolvente(self, envelope, security_elem):
        """Agrega firma XML (Signature) al envolvente con la llave privada."""
        # Encontrar Timestamp para firmar (siempre es el primero)
        ts_ns = "{http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd}"
        timestamp = security_elem.find(f"{ts_ns}Timestamp")

        if timestamp is None:
            raise ValueError("Timestamp no encontrado en Security")

        # Canonicalizar Timestamp para calcular DigestValue
        timestamp_canon = etree.tostring(
            timestamp,
            method="c14n",
            exclusive=True,
            with_comments=False,
        )
        hash_obj = hashes.Hash(hashes.SHA1())
        hash_obj.update(timestamp_canon)
        digest_value = base64.b64encode(hash_obj.finalize()).decode()

        # Crear SignedInfo
        sig_ns = self.NS["xd"]
        signed_info = etree.Element(
            f"{{{sig_ns}}}SignedInfo",
            nsmap={"xd": sig_ns},
        )

        # CanonicalizationMethod
        canon_method = etree.SubElement(signed_info, f"{{{sig_ns}}}CanonicalizationMethod")
        canon_method.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")

        # SignatureMethod
        sig_method = etree.SubElement(signed_info, f"{{{sig_ns}}}SignatureMethod")
        sig_method.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#rsa-sha1")

        # Reference (apunta al Timestamp)
        reference = etree.SubElement(signed_info, f"{{{sig_ns}}}Reference")
        reference.set("URI", "#_0")

        transforms = etree.SubElement(reference, f"{{{sig_ns}}}Transforms")
        transform = etree.SubElement(transforms, f"{{{sig_ns}}}Transform")
        transform.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")

        digest_method = etree.SubElement(reference, f"{{{sig_ns}}}DigestMethod")
        digest_method.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#sha1")

        digest_value_elem = etree.SubElement(reference, f"{{{sig_ns}}}DigestValue")
        digest_value_elem.text = digest_value

        # Canonicalizar SignedInfo
        signed_info_canon = etree.tostring(
            signed_info,
            method="c14n",
            exclusive=True,
            with_comments=False,
        )

        # Firmar con RSA-SHA1 — sign() hashea internamente, pasar datos crudos
        signature_bytes = self.cert.llave_privada.sign(
            signed_info_canon,
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        signature_value = base64.b64encode(signature_bytes).decode()

        # Crear elemento Signature
        signature = etree.SubElement(security_elem, f"{{{sig_ns}}}Signature")
        signature.set("xmlns", sig_ns)

        # Insertar SignedInfo dentro de Signature
        signature.append(signed_info)

        # SignatureValue
        sig_value = etree.SubElement(signature, f"{{{sig_ns}}}SignatureValue")
        sig_value.text = signature_value

        # KeyInfo con referencia al BinarySecurityToken
        key_info = etree.SubElement(signature, f"{{{sig_ns}}}KeyInfo")
        token_ref = etree.SubElement(key_info, f"{{{self.NS['o']}}}SecurityTokenReference")
        ref = etree.SubElement(token_ref, f"{{{self.NS['o']}}}Reference")
        # Encontrar el ID del token
        token = security_elem.find(
            f"{{{self.NS['o']}}}BinarySecurityToken"
        )
        if token is not None:
            token_id = token.get(f"{{{self.NS['u']}}}Id", "")
            ref.set("URI", f"#{token_id}")
            ref.set(
                "ValueType",
                "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-x509-token-profile-1.0#X509v3",
            )

    def _firmar_solicitud(self, solicitud_elem: etree._Element) -> None:
        """
        Agrega Signature XMLdsig dentro del elemento solicitud.

        Firma el elemento solicitud (sin Signature) con RSA-SHA1 y X509Certificate.
        El Signature queda como último hijo de solicitud.

        Args:
            solicitud_elem: Elemento <solicitud> ya construido con todos sus atributos
        """
        sig_ns = NS_XMLDSIG

        # 1. Dar ID al elemento para referenciarlo
        solicitud_elem.set("Id", "id-solicitud")

        # 2. Digest del elemento ANTES de agregar Signature
        solicitud_canon = etree.tostring(
            solicitud_elem,
            method="c14n",
            exclusive=True,
            with_comments=False,
        )
        hash_obj = hashes.Hash(hashes.SHA1())
        hash_obj.update(solicitud_canon)
        digest_value = base64.b64encode(hash_obj.finalize()).decode()

        # 3. SignedInfo
        signed_info = etree.Element(
            f"{{{sig_ns}}}SignedInfo",
            nsmap={"ds": sig_ns},
        )

        canon_method = etree.SubElement(signed_info, f"{{{sig_ns}}}CanonicalizationMethod")
        canon_method.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")

        sig_method = etree.SubElement(signed_info, f"{{{sig_ns}}}SignatureMethod")
        sig_method.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#rsa-sha1")

        reference = etree.SubElement(signed_info, f"{{{sig_ns}}}Reference")
        reference.set("URI", "#id-solicitud")

        transforms = etree.SubElement(reference, f"{{{sig_ns}}}Transforms")
        transform = etree.SubElement(transforms, f"{{{sig_ns}}}Transform")
        transform.set("Algorithm", "http://www.w3.org/2001/10/xml-exc-c14n#")

        digest_method = etree.SubElement(reference, f"{{{sig_ns}}}DigestMethod")
        digest_method.set("Algorithm", "http://www.w3.org/2000/09/xmldsig#sha1")

        digest_value_elem = etree.SubElement(reference, f"{{{sig_ns}}}DigestValue")
        digest_value_elem.text = digest_value

        # 4. Firmar SignedInfo canonicalizado
        signed_info_canon = etree.tostring(
            signed_info,
            method="c14n",
            exclusive=True,
            with_comments=False,
        )
        signature_bytes = self.cert.llave_privada.sign(
            signed_info_canon,
            padding.PKCS1v15(),
            hashes.SHA1(),
        )
        signature_value = base64.b64encode(signature_bytes).decode()

        # 5. Construir elemento Signature y adjuntar a solicitud
        signature = etree.SubElement(solicitud_elem, f"{{{sig_ns}}}Signature")
        signature.append(signed_info)

        sig_value_elem = etree.SubElement(signature, f"{{{sig_ns}}}SignatureValue")
        sig_value_elem.text = signature_value

        # KeyInfo con X509Certificate (no SecurityTokenReference)
        key_info = etree.SubElement(signature, f"{{{sig_ns}}}KeyInfo")
        x509_data = etree.SubElement(key_info, f"{{{sig_ns}}}X509Data")
        x509_cert = etree.SubElement(x509_data, f"{{{sig_ns}}}X509Certificate")
        x509_cert.text = self.cert.obtener_cer_base64()
