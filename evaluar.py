"""Mide qué tan bien lee tu analizador, comparando con los valores reales de las facturas.

Para cada campo cuenta aciertos y responde la pregunta importante:
con el umbral elegido, ¿cuántos errores se habrían aprobado solos?

Uso:
  python evaluar.py facturas --analyzer-id <id-de-tu-analizador> --umbral 0.85
"""
import argparse
import json
import re
import sys
from pathlib import Path

from reglas import UMBRAL_POR_DEFECTO, Campo, a_numero

NUMERICOS = {"totalAmount", "taxableBase", "vatAmount"}


def es_correcto(nombre: str, leido: object, real: object) -> bool:
    if leido in (None, ""):
        return False
    if nombre in NUMERICOS:
        return a_numero(leido) == float(real)
    if nombre == "invoiceDate":
        return str(leido)[:10] == str(real)
    return str(leido).strip().lower() == str(real).strip().lower()


def comparar(campos: dict[str, Campo], esperado: dict) -> list[dict]:
    filas = []
    for nombre, real in esperado.items():
        campo = campos.get(nombre)
        leido = campo.valor if campo else None
        filas.append({
            "campo": nombre,
            "leido": leido,
            "real": real,
            "correcto": es_correcto(nombre, leido, real),
            "confianza": campo.confianza if campo else None,
        })
    return filas


def resumir(filas: list[dict], umbral: float) -> dict:
    total = len(filas)
    aciertos = [f for f in filas if f["correcto"]]
    errores = [f for f in filas if not f["correcto"]]

    def media(items):
        valores = [f["confianza"] for f in items if f["confianza"] is not None]
        return sum(valores) / len(valores) if valores else None

    def pasa(f):
        return f["confianza"] is not None and f["confianza"] >= umbral

    return {
        "campos_evaluados": total,
        "aciertos": len(aciertos),
        "exactitud": len(aciertos) / total if total else None,
        "confianza_media_aciertos": media(aciertos),
        "confianza_media_errores": media(errores),
        "se_aprobarian_solos": sum(pasa(f) for f in filas),
        "van_a_revision": sum(not pasa(f) for f in filas),
        "errores_aprobados_solos": sum(1 for f in errores if pasa(f)),  # el riesgo real
        "aciertos_enviados_a_revision": sum(1 for f in aciertos if not pasa(f)),  # trabajo de más
    }


def porcentaje(x):
    return "n/d" if x is None else f"{x:.1%}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("carpeta", nargs="?", default="facturas")
    parser.add_argument("--analyzer-id", required=True)
    parser.add_argument("--umbral", type=float, default=UMBRAL_POR_DEFECTO)
    parser.add_argument("--valores", default="valores_reales.json")
    args = parser.parse_args()

    from app import analizar_con_azure  # import aquí: necesita el SDK de Azure

    reales = json.loads(Path(args.valores).read_text(encoding="utf-8"))
    todas: list[dict] = []
    for pdf in sorted(p for p in Path(args.carpeta).iterdir() if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}):
        clave = re.search(r"PRUEBA-\d{4}", pdf.name)
        if not clave or clave.group(0) not in reales:
            print(f"Sin valores reales para {pdf.name}, la omito")
            continue
        filas = comparar(analizar_con_azure(pdf, args.analyzer_id), reales[clave.group(0)])
        for f in filas:
            f["archivo"] = pdf.name
            marca = "ok " if f["correcto"] else "MAL"
            print(f"{marca} {pdf.name} {f['campo']}: leyó {f['leido']!r}, real {f['real']!r}, confianza {porcentaje(f['confianza'])}")
        todas += filas

    r = resumir(todas, args.umbral)
    print(f"\n--- Resumen con umbral {args.umbral:.0%} ---")
    print(f"Exactitud: {r['aciertos']}/{r['campos_evaluados']} ({porcentaje(r['exactitud'])})")
    print(f"Confianza media: aciertos {porcentaje(r['confianza_media_aciertos'])}, errores {porcentaje(r['confianza_media_errores'])}")
    print(f"Se aprobarían solos: {r['se_aprobarian_solos']}. Van a revisión: {r['van_a_revision']}")
    print(f"Errores que pasarían sin revisión: {r['errores_aprobados_solos']}  <- el riesgo")
    print(f"Datos correctos enviados a revisión: {r['aciertos_enviados_a_revision']}  <- trabajo de más")
    return 0


if __name__ == "__main__":
    sys.exit(main())