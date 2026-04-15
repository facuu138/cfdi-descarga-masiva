"""Modelos de datos para CFDI y descarga masiva."""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from enum import Enum


class EstadoSolicitud(str, Enum):
    """Estados posibles de una solicitud de descarga."""
    ACEPTADA = "1"
    EN_PROCESO = "2"
    TERMINADA = "3"
    ERROR = "4"
    RECHAZADA = "5"
    VENCIDA = "6"


class TipoComprobante(str, Enum):
    """Tipos de comprobantes descargables."""
    CFDI = "CFDI"
    RETENCIONES = "Retenciones"


class TipoSolicitud(str, Enum):
    """Tipos de solicitud (emitidas/recibidas)."""
    EMITIDAS = "emitidas"
    RECIBIDAS = "recibidas"


class SolicitudDescargaRequest(BaseModel):
    """Solicitud para descargar CFDIs."""
    rfc: str
    fecha_inicio: str  # YYYY-MM-DD
    fecha_fin: str     # YYYY-MM-DD
    tipo_comprobante: TipoComprobante = TipoComprobante.CFDI
    tipo_solicitud: TipoSolicitud = TipoSolicitud.EMITIDAS


class VerificacionSolicitudRequest(BaseModel):
    """Request para verificar estado de solicitud."""
    id_solicitud: str


class ConceptoLineaItem(BaseModel):
    """Concepto (línea de artículo) en CFDI."""
    clave_prod_serv: str
    cantidad: float
    clave_unidad: str
    unidad: Optional[str] = None
    descripcion: str
    valor_unitario: float
    importe: float
    descuento: Optional[float] = None
    objeto_imp: str
    iva_trasladado: Optional[float] = None
    iva_retenido: Optional[float] = None
    isr_retenido: Optional[float] = None
    ieps_trasladado: Optional[float] = None


class CFDI(BaseModel):
    """Modelo de un CFDI completo."""
    uuid: str
    fecha: datetime
    fecha_timbrado: datetime
    tipo_comprobante: str  # "I" (ingreso), "E" (egreso), etc.
    serie: Optional[str] = None
    folio: Optional[str] = None

    # Emisor
    rfc_emisor: str
    nombre_emisor: str
    regimen_fiscal_emisor: str

    # Receptor
    rfc_receptor: str
    nombre_receptor: str
    domicilio_fiscal_receptor: Optional[str] = None
    regimen_fiscal_receptor: str
    uso_cfdi: str

    # Moneda y totales
    moneda: str
    tipo_cambio: Optional[float] = None
    subtotal: float
    descuento: Optional[float] = None
    total: float

    # Impuestos
    total_iva_trasladado: Optional[float] = None
    total_iva_retenido: Optional[float] = None
    total_isr_retenido: Optional[float] = None
    total_ieps_trasladado: Optional[float] = None

    # Otros
    forma_pago: Optional[str] = None
    metodo_pago: Optional[str] = None
    lugar_expedicion: Optional[str] = None
    exportacion: Optional[str] = None
    no_certificado_sat: Optional[str] = None
    rfc_prov_certif: Optional[str] = None

    # XML raw
    xml_raw: str

    # Conceptos
    conceptos: List[ConceptoLineaItem] = []


class CorridaDescarga(BaseModel):
    """Registro de auditoría de una corrida de descarga."""
    rfc: str
    fecha_inicio: str
    fecha_fin: str
    tipo_solicitud: TipoSolicitud
    tipo_comprobante: TipoComprobante
    id_solicitud_sat: str
    estado_solicitud: EstadoSolicitud
    num_cfdis: int = 0
    ids_paquetes: List[str] = []
    created_at: datetime
