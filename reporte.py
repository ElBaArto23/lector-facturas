"""Genera reporte.html a partir de la carpeta resultados/ (un JSON por factura).

Uso:
  python reporte.py                 # lee resultados/ y crea reporte.html
  python reporte.py --abrir         # además lo abre en el navegador
"""
import argparse
import json
import webbrowser
from html import escape
from pathlib import Path

CAMPOS = ["invoiceNumber", "invoiceDate", "vendorName", "totalAmount"]
ETIQUETAS = {
    "aprobada_automaticamente": ("Aprobada sola", "ok"),
    "aprobada_por_persona": ("Aprobada por persona", "rev"),
    "aprobada_con_correcciones": ("Corregida por persona", "fix"),
    "rechazada_por_persona": ("Rechazada", "bad"),
}

CSS = """
:root{--bg:#fff;--fg:#1f2328;--mut:#656d76;--line:#d8dee4;--card:#f6f8fa;
--ok:#1a7f37;--okbg:#dafbe1;--rev:#9a6700;--revbg:#fff8c5;--fix:#0969da;--fixbg:#ddf4ff;--bad:#cf222e;--badbg:#ffebe9}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--mut:#8b949e;--line:#30363d;--card:#161b22;
--ok:#3fb950;--okbg:#12261e;--rev:#d29922;--revbg:#2d2208;--fix:#58a6ff;--fixbg:#0c2d6b;--bad:#f85149;--badbg:#3c1618}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif;padding:24px 16px}
main{max-width:1000px;margin:0 auto}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}
p.sub{color:var(--mut);margin:0 0 20px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card b{display:block;font-size:26px;line-height:1.1}.card span{color:var(--mut);font-size:13px}
.tablewrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:760px}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:middle}
th{background:var(--card);font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}tr:last-child td{border-bottom:0}
.badge{display:inline-block;padding:2px 9px;border-radius:99px;font-size:12px;font-weight:600;white-space:nowrap}
.badge.ok{color:var(--ok);background:var(--okbg)}.badge.rev{color:var(--rev);background:var(--revbg)}
.badge.fix{color:var(--fix);background:var(--fixbg)}.badge.bad{color:var(--bad);background:var(--badbg)}
.conf{display:flex;align-items:center;gap:8px;min-width:110px}
.bar{flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden}
.bar i{display:block;height:100%}.hi{background:var(--ok)}.lo{background:var(--rev)}.vlo{background:var(--bad)}
.pct{font-variant-numeric:tabular-nums;font-size:13px;min-width:44px;text-align:right}
.low{font-weight:700}
ul.rv{margin:0;padding-left:18px}ul.rv li{margin:3px 0}code{background:var(--card);padding:1px 5px;border-radius:4px;font-size:13px}
.empty{color:var(--mut);padding:14px}
"""


def barra(confianza, valor, umbral):
    if confianza is None:
        return '<span class="pct">n/d</span>'
    clase = "hi" if confianza >= umbral else ("lo" if confianza >= 0.5 else "vlo")
    negrita = "" if confianza >= umbral else " low"
    return (
        f'<div class="conf" title="Valor: {escape(str(valor))}">'
        f'<div class="bar"><i class="{clase}" style="width:{confianza * 100:.0f}%"></i></div>'
        f'<span class="pct{negrita}">{confianza:.0%}</span></div>'
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--resultados", default="resultados")
    parser.add_argument("--salida", default="reporte.html")
    parser.add_argument("--abrir", action="store_true")
    args = parser.parse_args()

    datos = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.resultados).glob("*.json"))]
    if not datos:
        print(f"No hay JSON en {args.resultados}. Ejecuta primero app.py.")
        return 1

    umbral = datos[0].get("umbral", 0.85)
    conteo = {k: 0 for k in ETIQUETAS}
    for d in datos:
        conteo[d["estado"]] = conteo.get(d["estado"], 0) + 1

    tarjetas = [f'<div class="card"><b>{len(datos)}</b><span>Facturas procesadas</span></div>']
    for estado, (texto, _) in ETIQUETAS.items():
        tarjetas.append(f'<div class="card"><b>{conteo.get(estado, 0)}</b><span>{texto}</span></div>')

    filas = []
    for d in datos:
        texto, clase = ETIQUETAS.get(d["estado"], (d["estado"], "rev"))
        celdas = "".join(
            f"<td>{barra(d['campos'].get(c, {}).get('confianza'), d['campos'].get(c, {}).get('valor'), umbral)}</td>"
            for c in CAMPOS
        )
        filas.append(
            f"<tr><td>{escape(d['archivo'])}</td><td><span class='badge {clase}'>{texto}</span></td>{celdas}</tr>"
        )

    revisiones = []
    for d in datos:
        if not d.get("motivos_de_revision"):
            continue
        decisiones = {x["campo"]: x for x in (d.get("revision_humana") or {}).get("decisiones", [])}
        items = []
        for m in d["motivos_de_revision"]:
            dec = decisiones.get(m["campo"])
            resultado = (
                f" → <b>{escape(dec['decision'])}</b> (valor: <code>{escape(str(dec['valor']))}</code>)" if dec else ""
            )
            items.append(f"<li><code>{escape(m['campo'])}</code>: {escape(m['motivo'])}{resultado}</li>")
        revisiones.append(f"<h3 style='font-size:14px;margin:14px 0 4px'>{escape(d['archivo'])}</h3><ul class='rv'>{''.join(items)}</ul>")

    cabeceras = "".join(f"<th>{c}</th>" for c in CAMPOS)
    html = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Reporte de facturas</title>
<style>{CSS}</style></head><body><main>
<h1>Reporte de facturas</h1>
<p class="sub">Confianza de cada campo contra el umbral de {umbral:.0%}. Lo que está por debajo se marca en negrita y se envió a revisión humana.</p>
<div class="cards">{''.join(tarjetas)}</div>
<h2>Confianza por campo</h2>
<div class="tablewrap"><table><thead><tr><th>Archivo</th><th>Estado</th>{cabeceras}</tr></thead><tbody>{''.join(filas)}</tbody></table></div>
<h2>Revisiones humanas</h2>
{''.join(revisiones) if revisiones else '<p class="empty">Ninguna factura necesitó revisión.</p>'}
</main></body></html>"""

    salida = Path(args.salida)
    salida.write_text(html, encoding="utf-8")
    print(f"Reporte creado: {salida.resolve()}")
    if args.abrir:
        webbrowser.open(salida.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())