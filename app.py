"""Mini proyecto: leer facturas con Content Understanding y pedir aprobación humana solo cuando hace falta.

Flujo por cada PDF:
  1. Analizar con tu analizador personalizado (autenticación con tu identidad, sin claves).
  2. Aplicar reglas: confianza por campo contra un umbral y montos que cuadren.
  3. Si todo pasa -> aprobada sola. Si no -> se pausa y una persona confirma o corrige.
  4. Guardar un JSON por factura con el estado y el rastro de la decisión.

Uso:
  python app.py --demo                                   # sin Azure, con datos simulados
  python app.py facturas/ --analyzer-id mi-analizador    # contra tu recurso real
"""
import argparse
import json
import os
import sys
from pathlib import Path

from reglas import UMBRAL_POR_DEFECTO, Campo, armar_resultado, revisar_campos

try:  # lee el archivo .env si existe (endpoint y clave), sin pisar variables ya definidas
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


# ---------------------------------------------------------------- Content Understanding
def obtener_credencial():
    """Clave en la variable CONTENTUNDERSTANDING_KEY si existe; si no, tu identidad (az login)."""
    clave = os.environ.get("CONTENTUNDERSTANDING_KEY", "").strip()
    if clave:
        from azure.core.credentials import AzureKeyCredential

        return AzureKeyCredential(clave)
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential()


def analizar_bytes_azure(
    contenido: bytes, analyzer_id: str, endpoint: str | None = None, mime: str = "application/pdf"
) -> dict[str, Campo]:
    """Llama al analizador con el archivo en bytes y devuelve los campos con valor y confianza."""
    # Imports aquí dentro para que --demo funcione sin instalar nada de Azure.
    from azure.ai.contentunderstanding import ContentUnderstandingClient

    endpoint = endpoint or os.environ["CONTENTUNDERSTANDING_ENDPOINT"]
    client = ContentUnderstandingClient(endpoint=endpoint, credential=obtener_credencial())

    poller = client.begin_analyze_binary(
        analyzer_id=analyzer_id,
        binary_input=contenido,
        content_type=mime,
    )
    resultado = poller.result()

    campos: dict[str, Campo] = {}
    for nombre, campo in (resultado.contents[0].fields or {}).items():
        if campo:
            campos[nombre] = Campo(
                nombre=nombre,
                valor=getattr(campo, "value", None),
                confianza=getattr(campo, "confidence", None),
            )
    return campos


def analizar_con_azure(ruta_pdf: Path, analyzer_id: str) -> dict[str, Campo]:
    """Igual que analizar_bytes_azure, pero leyendo el PDF desde disco."""
    import mimetypes

    mime = mimetypes.guess_type(str(ruta_pdf))[0] or "application/pdf"
    return analizar_bytes_azure(Path(ruta_pdf).read_bytes(), analyzer_id, mime=mime)


def analizar_demo(ruta_pdf: Path) -> dict[str, Campo]:
    """Resultados simulados para probar el flujo sin Azure y sin costos."""
    demo = {
        "PRUEBA-0001": [
            ("invoiceNumber", "PRUEBA-0001", 0.926),
            ("invoiceDate", "2026-09-01", 0.897),
            ("vendorName", "Empresa Demo Colombia S.A.S.", 0.95),
            ("totalAmount", 406980, 0.95),
            ("taxableBase", 342000, 0.93),
            ("vatAmount", 64980, 0.93),
        ],
        "PRUEBA-0002": [
            ("invoiceNumber", "PRUEBA-0002", 0.97),
            ("invoiceDate", "2026-09-02", 0.96),
            ("vendorName", "Empresa Demo Colombia S.A.S.", 0.96),
            ("totalAmount", 446250, 0.667),  # confianza baja a propósito
            ("taxableBase", 375000, 0.95),
            ("vatAmount", 71250, 0.95),
        ],
        "PRUEBA-0003": [
            ("invoiceNumber", "PRUEBA-0003", 0.97),
            ("invoiceDate", "2026-09-03", 0.95),
            ("vendorName", "Empresa Demo Colombia S.A.S.", 0.96),
            ("totalAmount", 416500, 0.95),
            ("taxableBase", 350000, 0.94),
            ("vatAmount", 66500, 0.94),
        ],
    }
    clave = next((k for k in demo if k in ruta_pdf.name.upper()), "PRUEBA-0001")
    return {n: Campo(n, v, c) for n, v, c in demo[clave]}


# ---------------------------------------------------------------- Aprobación humana
def pedir_aprobacion(archivo: str, campos: dict[str, Campo], motivos: list[tuple[str, str]]) -> dict:
    """Pausa el flujo y le pregunta a una persona. Devuelve las decisiones tomadas."""
    print(f"\n=== REVISIÓN HUMANA: {archivo} ===")
    decisiones = []
    for nombre, motivo in motivos:
        campo = campos.get(nombre)
        leido = campo.valor if campo else None
        print(f"- {nombre}: se leyó {leido!r}. Motivo: {motivo}")
        respuesta = input("  ¿Es correcto? [s/n]: ").strip().lower()
        if respuesta == "s":
            decisiones.append({"campo": nombre, "motivo": motivo, "decision": "confirmado", "valor": leido})
        else:
            nuevo = input("  Escribe el valor correcto (vacío = rechazar la factura): ").strip()
            if nuevo:
                decisiones.append({"campo": nombre, "motivo": motivo, "decision": "corregido", "valor": nuevo})
                if campo:
                    campo.valor = nuevo
            else:
                decisiones.append({"campo": nombre, "motivo": motivo, "decision": "rechazado", "valor": leido})
    return {"decisiones": decisiones}


# ---------------------------------------------------------------- Flujo principal
def procesar(ruta_pdf: Path, analyzer_id: str | None, umbral: float, demo: bool) -> dict:
    campos = analizar_demo(ruta_pdf) if demo else analizar_con_azure(ruta_pdf, analyzer_id)
    motivos = revisar_campos(campos, umbral)
    decisiones = pedir_aprobacion(ruta_pdf.name, campos, motivos)["decisiones"] if motivos else []
    return armar_resultado(ruta_pdf.name, campos, motivos, decisiones, umbral)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("carpeta", nargs="?", default="facturas", help="carpeta con los PDF (una factura por archivo)")
    parser.add_argument("--analyzer-id", help="id del analizador guardado en Content Understanding")
    parser.add_argument("--umbral", type=float, default=UMBRAL_POR_DEFECTO, help="confianza mínima, de 0 a 1")
    parser.add_argument("--salida", default="resultados", help="carpeta donde se guardan los JSON")
    parser.add_argument("--demo", action="store_true", help="usa datos simulados, sin llamar a Azure")
    args = parser.parse_args()

    if not args.demo and not args.analyzer_id:
        parser.error("falta --analyzer-id (o usa --demo)")

    carpeta = Path(args.carpeta)
    pdfs = sorted(p for p in carpeta.iterdir() if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"})
    if not pdfs:
        print(f"No encontré PDF en {carpeta.resolve()}")
        return 1

    salida = Path(args.salida)
    salida.mkdir(exist_ok=True)

    for pdf in pdfs:
        resultado = procesar(pdf, args.analyzer_id, args.umbral, args.demo)
        (salida / f"{pdf.stem}.json").write_text(
            json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"{pdf.name}: {resultado['estado']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())