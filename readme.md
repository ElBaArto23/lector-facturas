# Mini proyecto: facturas con Content Understanding y aprobación humana

Lee facturas con tu analizador personalizado y solo pide revisión a una persona cuando la confianza es baja o los montos no cuadran.

## Archivos

- `reglas.py`: las reglas (umbral de confianza y montos que cuadren). No usa Azure.
- `app.py`: llama al analizador, aplica las reglas, pausa para la aprobación y guarda un JSON por factura.
- `requirements.txt`: dependencias.

## 1. Prueba sin Azure (sin costo)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
mkdir facturas                  # copia aquí 2 o 3 PDF de prueba
python app.py --demo
```

El modo `--demo` usa resultados simulados. La factura PRUEBA-0002 trae el total con 66.7 % de confianza a propósito, para que veas la pausa y la pregunta.

## 2. Prueba contra tu recurso real

Antes de empezar, hay tres cosas por dejar listas:

1. **Guardar el analizador.** En Content Understanding Studio, en tu proyecto `cu-lab-facturas`, pulsa **Build analyzer** y anota el **id** del analizador. Con solo **Run analysis** no queda guardado para usarlo desde código.
2. **Permiso con tu identidad.** En el portal de Azure, en el recurso de Foundry (`lector-agente`), ve a *Access control (IAM)* y asígnate el rol **Cognitive Services User**. Con esto no se usa ninguna clave.
3. **Iniciar sesión.** Ejecuta `az login` en la terminal.

Luego:

```bash
set CONTENTUNDERSTANDING_ENDPOINT=https://<tu-recurso>.services.ai.azure.com/
python app.py facturas --analyzer-id <id-de-tu-analizador>
```

(En PowerShell usa `$env:CONTENTUNDERSTANDING_ENDPOINT="https://..."`.)

Si falla con un error sobre modelos por defecto, el recurso necesita tener asignados los modelos de chat y de inserción por defecto. Los pasos exactos están en la documentación oficial del SDK, y conviene comprobarlos antes de insistir.

## Qué hace con cada factura

| Situación | Estado que queda |
|---|---|
| Todos los campos sobre el umbral y montos cuadran | `aprobada_automaticamente` |
| Alguna confianza baja o campo faltante, y la persona confirma | `aprobada_por_persona` |
| La persona corrige algún valor | `aprobada_con_correcciones` |
| La persona rechaza | `rechazada_por_persona` |

Los resultados quedan en `resultados/<factura>.json`, con el umbral usado, la hora, los motivos de revisión y la decisión humana.

## Para ajustar

- `--umbral 0.9` hace el filtro más estricto.
- Si agregas al analizador los campos `taxableBase` (base gravable) y `vatAmount` (IVA), el proyecto comprueba que base + IVA = total.

## Página web (Streamlit)

Es lo mismo que `app.py`, pero en el navegador y con botones en lugar de preguntas en la terminal.

```bash
pip install -r requirements.txt
streamlit run web.py
```

Se abre en `http://localhost:8501`. Solo funciona en tu computador mientras el comando esté corriendo.

- **Modo Demo (sin Azure):** datos simulados. Sirve para ver la interfaz. Sube cualquier PDF; si su nombre contiene `PRUEBA-0002`, simula el total con 66.7 %.
- **Modo Azure real:** escribe el endpoint y el id de tu analizador, y pulsa **Probar conexión**. Muestra paso a paso si el endpoint es válido, si Azure acepta tu sesión (sin claves) y si el analizador existe, con el motivo si algo falla (sin `az login`, sin el rol *Cognitive Services User*, analizador inexistente).
- **Procesar:** sube una factura, pulsa **Analizar** y verás los campos con su confianza. Si algo está bajo el umbral, eliges **Confirmar**, **Corregir** o **Rechazar** y se guarda.
- **Historial:** lista de las facturas ya guardadas en `resultados/`.

Los JSON que guarda la web tienen el mismo formato que los de `app.py`, así que `reporte.py` y `evaluar.py` funcionan con ambos.

## 3. Medir qué tan bien lee el analizador (con tus 10 facturas)

La carpeta `facturas/` trae las 10 facturas, una por archivo, y `valores_reales.json` trae los valores correctos de cada una (se comprobaron contra el texto de los PDF).

```bash
python evaluar.py facturas --analyzer-id <id-de-tu-analizador> --umbral 0.85
```

Imprime, por cada campo, lo que leyó contra el valor real, y al final un resumen:

- **Exactitud:** cuántos campos acertó.
- **Errores que pasarían sin revisión:** datos mal leídos con confianza por encima del umbral. Es el riesgo real.
- **Datos correctos enviados a revisión:** aciertos con confianza baja. Es trabajo de más.

Prueba con `--umbral 0.7`, `0.85` y `0.95` y mira cómo se mueven esas dos cifras. Es la decisión que se toma en un proyecto real.

Dos advertencias: con 10 facturas es una práctica, no una medición confiable, y como diseñaste el analizador mirando estas mismas facturas, el resultado sale algo más optimista de lo que sería con facturas nuevas.

## Cuando termines

Borra los modelos desplegados y los recursos que creaste para este laboratorio, para no generar costos.

## Aviso

El código de la parte de Azure sigue la documentación oficial del SDK, pero no pude ejecutarlo contra tu recurso. La lógica de decisión sí se probó en modo simulado. Si algo falla con el SDK, copia el mensaje de error completo y lo corregimos.