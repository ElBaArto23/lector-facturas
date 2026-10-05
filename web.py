"""Página web local para procesar facturas con aprobación humana.

Uso:
  streamlit run web.py

Modo Demo: datos simulados, sin Azure.
Modo Azure real: usa tu identidad (az login), sin claves. El botón "Probar conexión" comprueba
que el endpoint responde, que tu identidad tiene permiso y que el analizador existe.
"""
import json
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from app import analizar_bytes_azure, analizar_demo
from reglas import UMBRAL_POR_DEFECTO, armar_resultado, revisar_campos

CARPETA = Path("resultados")
ESTADOS = {
    "aprobada_automaticamente": "Aprobada sola",
    "aprobada_por_persona": "Aprobada por persona",
    "aprobada_con_correcciones": "Corregida por persona",
    "rechazada_por_persona": "Rechazada",
}


# ---------------------------------------------------------------- Conexión a Azure
def probar_conexion(endpoint: str, analyzer_id: str) -> list[dict]:
    """Comprueba la conexión paso a paso. Nunca lanza error: devuelve qué pasó en cada paso."""
    pasos: list[dict] = []

    if not endpoint.startswith("https://"):
        return [{"paso": "Endpoint", "ok": False, "detalle": "Debe empezar por https:// (ej. https://mi-recurso.services.ai.azure.com/)"}]
    pasos.append({"paso": "Endpoint", "ok": True, "detalle": endpoint})

    if not analyzer_id.strip():
        pasos.append({"paso": "Analizador", "ok": False, "detalle": "Falta el id del analizador (se obtiene al pulsar Build analyzer en el Studio)."})
        return pasos

    try:
        from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
        from azure.ai.contentunderstanding import ContentUnderstandingClient
        from app import obtener_credencial
    except ImportError as e:
        pasos.append({"paso": "Librerías", "ok": False, "detalle": f"Falta instalar: {e}. Ejecuta pip install -r requirements.txt"})
        return pasos

    inicio = time.perf_counter()
    try:
        client = ContentUnderstandingClient(endpoint=endpoint, credential=obtener_credencial())
        analizador = client.get_analyzer(analyzer_id.strip())
        ms = (time.perf_counter() - inicio) * 1000
        pasos.append({"paso": "Identidad", "ok": True, "detalle": "Azure aceptó la credencial (" + ("clave de recurso" if os.environ.get("CONTENTUNDERSTANDING_KEY", "").strip() else "tu sesión, sin claves") + ")."})
        pasos.append({"paso": "Analizador", "ok": True, "detalle": f"Encontrado: {getattr(analizador, 'analyzer_id', analyzer_id)} · respuesta en {ms:.0f} ms"})
    except ClientAuthenticationError:
        pasos.append({"paso": "Identidad", "ok": False, "detalle": "Credencial no válida. Si usas clave, revisa CONTENTUNDERSTANDING_KEY; si no, ejecuta az login y vuelve a probar."})
    except ResourceNotFoundError:
        pasos.append({"paso": "Identidad", "ok": True, "detalle": "Azure respondió y aceptó tu sesión."})
        pasos.append({"paso": "Analizador", "ok": False, "detalle": f"No existe un analizador con id '{analyzer_id}'. ¿Pulsaste Build analyzer en el Studio?"})
    except HttpResponseError as e:
        if e.status_code in (401, 403):
            detalle = "Sin permiso. Asígnate el rol Cognitive Services User en el recurso de Foundry (Access control IAM)."
        else:
            detalle = f"Azure respondió con error {e.status_code}: {e.message}"
        pasos.append({"paso": "Servicio", "ok": False, "detalle": detalle})
    except Exception as e:  # red caída, endpoint mal escrito, etc.
        pasos.append({"paso": "Servicio", "ok": False, "detalle": f"No se pudo conectar: {type(e).__name__}: {e}"})
    return pasos


# ---------------------------------------------------------------- Guardado
def guardar(actual: dict, decisiones: list[dict]) -> dict:
    resultado = armar_resultado(
        actual["nombre"], actual["campos"], actual["motivos"], decisiones, actual["umbral"]
    )
    CARPETA.mkdir(exist_ok=True)
    (CARPETA / f"{Path(actual['nombre']).stem}.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resultado


def tabla_campos(actual: dict) -> pd.DataFrame:
    en_revision = {c for c, _ in actual["motivos"]}
    filas = []
    for nombre, campo in actual["campos"].items():
        filas.append({
            "Campo": nombre,
            "Valor leído": "" if campo.valor is None else str(campo.valor),
            "Confianza": None if campo.confianza is None else round(campo.confianza * 100, 1),
            "Estado": "Revisar" if nombre in en_revision else "OK",
        })
    return pd.DataFrame(filas)


def historial() -> pd.DataFrame:
    filas = []
    for p in sorted(CARPETA.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        confs = [c["confianza"] for c in d["campos"].values() if c["confianza"] is not None]
        filas.append({
            "Archivo": d["archivo"],
            "Estado": ESTADOS.get(d["estado"], d["estado"]),
            "Campos en revisión": len(d["motivos_de_revision"]),
            "Confianza mínima": round(min(confs) * 100, 1) if confs else None,
            "Hora (UTC)": d["procesada_utc"][:19].replace("T", " "),
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- Página
st.set_page_config(page_title="Facturas con aprobación humana", layout="wide")
st.title("Facturas con aprobación humana")
st.caption("Lee la factura con Content Understanding y pide revisión a una persona solo cuando la confianza es baja.")

with st.sidebar:
    st.header("Configuración")
    modo = st.radio("Modo", ["Demo (sin Azure)", "Azure real"], key="modo")
    umbral = st.slider("Umbral de confianza", 0.50, 0.99, UMBRAL_POR_DEFECTO, 0.01, key="umbral")
    endpoint = analyzer_id = ""
    if modo == "Azure real":
        endpoint = st.text_input("Endpoint", os.environ.get("CONTENTUNDERSTANDING_ENDPOINT", ""), key="endpoint")
        analyzer_id = st.text_input("Id del analizador", key="analyzer_id")
        if st.button("Probar conexión", key="probar"):
            with st.spinner("Probando..."):
                st.session_state["conexion"] = probar_conexion(endpoint, analyzer_id)
        for paso in st.session_state.get("conexion", []):
            (st.success if paso["ok"] else st.error)(f"**{paso['paso']}**: {paso['detalle']}")
    else:
        st.info("Modo demo: los resultados son simulados y no se llama a Azure.")

tab_procesar, tab_historial = st.tabs(["Procesar", "Historial"])

with tab_procesar:
    archivo = st.file_uploader("Sube una factura (un archivo por factura)", type=["pdf", "png", "jpg", "jpeg"], key="archivo")
    if archivo and st.button("Analizar", type="primary", key="analizar"):
        try:
            if modo == "Demo (sin Azure)":
                campos = analizar_demo(Path(archivo.name))
            else:
                with st.spinner("Analizando con Content Understanding..."):
                    campos = analizar_bytes_azure(archivo.getvalue(), analyzer_id.strip(), endpoint or None, archivo.type)
            st.session_state["actual"] = {
                "nombre": archivo.name,
                "campos": campos,
                "motivos": revisar_campos(campos, umbral),
                "umbral": umbral,
            }
            st.session_state.pop("guardado", None)
        except Exception as e:
            st.error(f"No se pudo analizar: {type(e).__name__}: {e}")

    actual = st.session_state.get("actual")
    if actual:
        st.subheader(actual["nombre"])
        st.dataframe(
            tabla_campos(actual),
            hide_index=True,
            column_config={
                "Confianza": st.column_config.ProgressColumn("Confianza", min_value=0, max_value=100, format="%.1f%%"),
            },
        )

        if "guardado" in st.session_state:
            r = st.session_state["guardado"]
            st.success(f"Guardado como **{ESTADOS[r['estado']]}** en resultados/{Path(actual['nombre']).stem}.json")
        elif not actual["motivos"]:
            st.success(f"Todos los campos superan el umbral de {actual['umbral']:.0%} y los montos cuadran: se aprueba sola.")
            if st.button("Guardar resultado", key="guardar_auto"):
                st.session_state["guardado"] = guardar(actual, [])
                st.rerun()
        else:
            st.warning(f"{len(actual['motivos'])} punto(s) necesitan que una persona decida.")
            elecciones = []
            for i, (campo, motivo) in enumerate(actual["motivos"]):
                leido = actual["campos"][campo].valor if campo in actual["campos"] else None
                with st.container(border=True):
                    st.markdown(f"**{campo}**: se leyó `{leido}`")
                    st.caption(motivo)
                    eleccion = st.radio("Decisión", ["Confirmar", "Corregir", "Rechazar"], horizontal=True, key=f"dec_{i}")
                    nuevo = st.text_input("Valor correcto", key=f"val_{i}") if eleccion == "Corregir" else ""
                    elecciones.append((campo, motivo, leido, eleccion, nuevo))

            if st.button("Guardar decisión", type="primary", key="guardar_rev"):
                faltan = [c for c, _, _, e, n in elecciones if e == "Corregir" and not n.strip()]
                if faltan:
                    st.error(f"Escribe el valor correcto de: {', '.join(faltan)}")
                else:
                    decisiones = []
                    for campo, motivo, leido, eleccion, nuevo in elecciones:
                        if eleccion == "Confirmar":
                            decisiones.append({"campo": campo, "motivo": motivo, "decision": "confirmado", "valor": leido})
                        elif eleccion == "Corregir":
                            decisiones.append({"campo": campo, "motivo": motivo, "decision": "corregido", "valor": nuevo.strip()})
                            actual["campos"][campo].valor = nuevo.strip()
                        else:
                            decisiones.append({"campo": campo, "motivo": motivo, "decision": "rechazado", "valor": leido})
                    st.session_state["guardado"] = guardar(actual, decisiones)
                    st.rerun()

with tab_historial:
    df = historial()
    if df.empty:
        st.info("Aún no hay facturas guardadas.")
    else:
        st.dataframe(df, hide_index=True)