"""Cargador de certificado e.firma y llave privada."""
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from cryptography import x509


class CertificadoEfirma:
    """Carga y maneja certificado X.509 + llave privada."""

    def __init__(self, ruta_cer: str, ruta_key: str, contraseña: str):
        """
        Carga certificado y llave privada.

        Args:
            ruta_cer: Ruta a archivo .cer
            ruta_key: Ruta a archivo .key encriptado
            contraseña: Contraseña para desencriptar .key
        """
        self.ruta_cer = Path(ruta_cer)
        self.ruta_key = Path(ruta_key)
        self.contraseña = contraseña.encode() if isinstance(contraseña, str) else contraseña

        if not self.ruta_cer.exists():
            raise FileNotFoundError(f"Certificado no encontrado: {self.ruta_cer}")
        if not self.ruta_key.exists():
            raise FileNotFoundError(f"Llave privada no encontrada: {self.ruta_key}")

        self._cargar_certificado()
        self._cargar_llave()

    def _cargar_certificado(self):
        """Lee y parsea el certificado X.509."""
        datos_cer = self.ruta_cer.read_bytes()
        self.certificado = x509.load_der_x509_certificate(
            datos_cer, backend=default_backend()
        )

    def _cargar_llave(self):
        """Lee y desencripta la llave privada (formato DER/PKCS#8)."""
        datos_key = self.ruta_key.read_bytes()
        # SAT usa PKCS#8 encriptado en formato DER (no PEM)
        try:
            self.llave_privada = serialization.load_der_private_key(
                datos_key, password=self.contraseña, backend=default_backend()
            )
        except Exception:
            # Intenta PEM como fallback
            self.llave_privada = serialization.load_pem_private_key(
                datos_key, password=self.contraseña, backend=default_backend()
            )

    def obtener_cer_base64(self) -> str:
        """Retorna certificado en base64 para BinarySecurityToken."""
        import base64

        datos_cer = self.ruta_cer.read_bytes()
        return base64.b64encode(datos_cer).decode("ascii")

    def obtener_fingerprint(self) -> str:
        """Retorna fingerprint SHA-1 del certificado."""
        import base64

        from cryptography.hazmat.primitives import hashes

        huella = self.certificado.fingerprint(hashes.SHA1())
        return base64.b64encode(huella).decode("ascii")
