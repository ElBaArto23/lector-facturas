"""Reglas de decisión, sin Azure.

Deciden si una factura se aprueba sola o necesita revisión humana.
Están separadas del código que llama al servicio para poder probarlas sin costos.
"""
from dataclasses import dataclass

UMBRAL_POR_DEFECTO = 0.85
CAMPOS_OBLIGATORIOS = ["invoiceNumber", "invoiceDate", "vendorName", "totalAmount"]
# Opcionales: si el analizador también los extrae, se usan para comprobar que los montos cuadran.
CAMPO_BASE = "taxableBase"
CAMPO_IVA = "vatAmount"
TOLERANCIA_MONTOS = 1.0  # pesos


@dataclass
class Campo:
    nombre: str
    valor: object
    confianza: float | None


def a_numero(valor: object) -> float | None:
    """Convierte un valor a número. Si llega como texto, asume pesos sin decimales ($1.040.060)."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = "".join(ch for ch in str(valor) if ch.isdigit())
    return float(texto) if texto else None


def validar_montos(campos: dict[str, Campo]) -> list[tuple[str, str]]:
    """Reglas de negocio: el total es positivo y, si hay base e IVA, la suma cuadra."""
    motivos: list[tuple[str, str]] = []
    total = a_numero(campos["totalAmount"].valor) if "totalAmount" in campos else None
    if total is not None and total <= 0:
        motivos.append(("totalAmount", "el total debe ser mayor que cero"))

    base = a_numero(campos[CAMPO_BASE].valor) if CAMPO_BASE in campos else None
    iva = a_numero(campos[CAMPO_IVA].valor) if CAMPO_IVA in campos else None
    if None not in (base, iva, total):
        if abs((base + iva) - total) > TOLERANCIA_MONTOS:
            motivos.append(
                ("totalAmount", f"base + IVA = {base + iva:,.0f}, pero el total leído es {total:,.0f}")
            )
    return motivos


def revisar_campos(campos: dict[str, Campo], umbral: float = UMBRAL_POR_DEFECTO) -> list[tuple[str, str]]:
    """Devuelve (campo, motivo) por cada cosa que necesita revisión. Lista vacía = aprobada sola."""
    motivos: list[tuple[str, str]] = []
    for nombre in CAMPOS_OBLIGATORIOS:
        campo = campos.get(nombre)
        if campo is None or campo.valor in (None, ""):
            motivos.append((nombre, "no se encontró el campo"))
        elif campo.confianza is None:
            motivos.append((nombre, "el servicio no devolvió confianza"))
        elif campo.confianza < umbral:
            motivos.append((nombre, f"confianza {campo.confianza:.1%} por debajo del umbral {umbral:.0%}"))
    motivos += validar_montos(campos)
    return motivos


# ---------------------------------------------------------------- Estado y resultado (compartido)
def estado_final(motivos: list[tuple[str, str]], decisiones: list[dict]) -> str:
    """Estado de la factura según si hubo revisión y qué decidió la persona."""
    if not motivos:
        return "aprobada_automaticamente"
    if any(d["decision"] == "rechazado" for d in decisiones):
        return "rechazada_por_persona"
    if any(d["decision"] == "corregido" for d in decisiones):
        return "aprobada_con_correcciones"
    return "aprobada_por_persona"


def armar_resultado(
    archivo: str,
    campos: dict[str, Campo],
    motivos: list[tuple[str, str]],
    decisiones: list[dict],
    umbral: float,
) -> dict:
    """Arma el diccionario que se guarda como JSON (mismo formato en terminal y en la web)."""
    from datetime import datetime, timezone

    return {
        "archivo": archivo,
        "estado": estado_final(motivos, decisiones),
        "umbral": umbral,
        "procesada_utc": datetime.now(timezone.utc).isoformat(),
        "campos": {n: {"valor": c.valor, "confianza": c.confianza} for n, c in campos.items()},
        "motivos_de_revision": [{"campo": c, "motivo": m} for c, m in motivos],
        "revision_humana": {"decisiones": decisiones} if motivos else None,
    }