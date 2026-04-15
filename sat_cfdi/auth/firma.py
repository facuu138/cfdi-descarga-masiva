"""Firma XMLdsig enveloped para solicitudes SAT (SolicitaDescarga, VerificaSolicitudDescarga)."""
import base64
from lxml import etree
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"
_C14N_INCLUSIVO = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
_ENVELOPED = f"{NS_DSIG}enveloped-signature"
_RSA_SHA1 = f"{NS_DSIG}rsa-sha1"
_SHA1 = f"{NS_DSIG}sha1"


def firmar_elemento_enveloped(
    elemento: etree._Element,
    llave_privada,
    certificado,
) -> None:
    """
    Agrega firma XMLdsig enveloped al elemento como último hijo.

    Algoritmo:
    - C14N inclusivo sobre el elemento (sin Signature)
    - SHA1 digest de lo anterior
    - RSA-SHA1 sobre C14N de SignedInfo
    - KeyInfo: X509Data con IssuerSerial + Certificate

    Args:
        elemento: Elemento lxml a firmar (modificado in-place)
        llave_privada: cryptography RSA private key
        certificado: cryptography X.509 Certificate
    """
    # 1. C14N del elemento SIN Signature → DigestValue
    elemento_c14n = etree.tostring(elemento, method="c14n", exclusive=False, with_comments=False)
    hash_digest = hashes.Hash(hashes.SHA1())
    hash_digest.update(elemento_c14n)
    digest_value = base64.b64encode(hash_digest.finalize()).decode()

    # 2. Construir SignedInfo
    signed_info = etree.Element(f"{{{NS_DSIG}}}SignedInfo", nsmap={"dsig": NS_DSIG})

    canon_method = etree.SubElement(signed_info, f"{{{NS_DSIG}}}CanonicalizationMethod")
    canon_method.set("Algorithm", _C14N_INCLUSIVO)

    sig_method = etree.SubElement(signed_info, f"{{{NS_DSIG}}}SignatureMethod")
    sig_method.set("Algorithm", _RSA_SHA1)

    reference = etree.SubElement(signed_info, f"{{{NS_DSIG}}}Reference")
    reference.set("URI", "")

    transforms = etree.SubElement(reference, f"{{{NS_DSIG}}}Transforms")
    transform = etree.SubElement(transforms, f"{{{NS_DSIG}}}Transform")
    transform.set("Algorithm", _ENVELOPED)

    digest_method = etree.SubElement(reference, f"{{{NS_DSIG}}}DigestMethod")
    digest_method.set("Algorithm", _SHA1)

    digest_value_elem = etree.SubElement(reference, f"{{{NS_DSIG}}}DigestValue")
    digest_value_elem.text = digest_value

    # 3. C14N SignedInfo → RSA-SHA1 firma
    signed_info_c14n = etree.tostring(signed_info, method="c14n", exclusive=False, with_comments=False)
    firma_bytes = llave_privada.sign(signed_info_c14n, padding.PKCS1v15(), hashes.SHA1())
    firma_b64 = base64.b64encode(firma_bytes).decode()

    # 4. Construir Signature y adjuntar al elemento
    signature = etree.SubElement(elemento, f"{{{NS_DSIG}}}Signature", nsmap={None: NS_DSIG})
    signature.append(signed_info)

    sig_value = etree.SubElement(signature, f"{{{NS_DSIG}}}SignatureValue")
    sig_value.text = firma_b64

    # 5. KeyInfo: X509Data con IssuerSerial + Certificate
    key_info = etree.SubElement(signature, f"{{{NS_DSIG}}}KeyInfo")
    x509_data = etree.SubElement(key_info, f"{{{NS_DSIG}}}X509Data")

    issuer_serial = etree.SubElement(x509_data, f"{{{NS_DSIG}}}X509IssuerSerial")
    issuer_name_elem = etree.SubElement(issuer_serial, f"{{{NS_DSIG}}}X509IssuerName")
    issuer_name_elem.text = certificado.issuer.rfc4514_string()
    serial_num_elem = etree.SubElement(issuer_serial, f"{{{NS_DSIG}}}X509SerialNumber")
    serial_num_elem.text = str(certificado.serial_number)

    x509_cert_elem = etree.SubElement(x509_data, f"{{{NS_DSIG}}}X509Certificate")
    cert_der = certificado.public_bytes(serialization.Encoding.DER)
    x509_cert_elem.text = base64.b64encode(cert_der).decode()
