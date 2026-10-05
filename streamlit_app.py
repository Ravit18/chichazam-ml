import os
import sys
import sqlite3
import tempfile
import threading
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "deteccion_canciones"))  # para importar utils.*

from utils.hashing import hashes
from utils.patterns import peaks
from utils.spectrogram import HOP, SR, generate_spectrogram
from utils.fingerprint_db import identify

DB_FILENAME = "fingerprints.db"
DB_PATH = PROJECT_ROOT / DB_FILENAME
FINGERPRINTS_REPO = "pollitoconpapass/chichazam-fingerprints"  # se sube con scripts/upload_db_to_huggingface.py

st.set_page_config(page_title="Chichazam", page_icon="🇵🇪", layout="centered")


# === Helpers ===
def get_setting(key: str) -> str | None:
    # Primero variables de entorno, luego los secrets de Streamlit (si existen)
    if os.getenv(key):
        return os.getenv(key)
    try:
        return st.secrets.get(key)
    except Exception:
        return None


@st.cache_resource(show_spinner="Cargando la base de datos de huellas...")
def load_db():
    # En local se usa el fingerprints.db generado por main_almacenar.py.
    # En la nube no existe (pesa demasiado para GitHub), asi que se baja de Hugging Face.
    if not DB_PATH.exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download(
            repo_id=get_setting("FINGERPRINTS_REPO") or FINGERPRINTS_REPO,
            filename=DB_FILENAME,
            repo_type="dataset",
            token=get_setting("HF_TOKEN"),
            local_dir=str(PROJECT_ROOT),
        )

    # Solo lectura: la app nunca escribe en la BD (la tabla temporal de find_matches vive aparte).
    # La conexion se comparte entre sesiones y esa tabla temporal es por conexion: de ahi el lock
    conn = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True, check_same_thread=False)
    return conn, threading.Lock()


def detect(audio_bytes: bytes, suffix: str) -> list[dict]:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        hashes_query = hashes(peaks(generate_spectrogram(tmp_path)))
    finally:
        os.unlink(tmp_path)

    with lock:
        return identify(conn, hashes_query, top_k=5, min_score=5)


# === UI ===
st.title("Chichazam 🇵🇪")
st.caption("Shazam para música peruana: graba o sube un fragmento y te decimos qué canción es.")

try:
    conn, lock = load_db()
except Exception as exc:
    st.error(
        f"No se pudo cargar `{DB_FILENAME}` ({exc}). Genérala con `deteccion_canciones/main_almacenar.py` "
        "o súbela a Hugging Face con `scripts/upload_db_to_huggingface.py`."
    )
    st.stop()

with lock:
    total_canciones = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
st.sidebar.metric("Canciones en la base de datos", total_canciones)

tab_grabar, tab_subir = st.tabs(["🎙️ Grabar", "📁 Subir archivo"])
with tab_grabar:
    grabacion = st.audio_input("Graba unos 10 segundos de la canción")
with tab_subir:
    archivo = st.file_uploader("Sube un fragmento de audio", type=["wav", "mp3", "ogg", "flac", "m4a"])

audio = grabacion or archivo
if audio is not None:
    if archivo is not None and audio is archivo:
        st.audio(audio)

    try:
        with st.spinner("Escuchando..."):
            resultados = detect(audio.getvalue(), Path(audio.name).suffix or ".wav")
    except Exception as exc:
        st.error(f"No se pudo procesar el audio ({exc})")
        st.stop()

    if not resultados:
        st.warning("No encontramos esta canción en la base de datos. Prueba con un fragmento más largo o con menos ruido.")
        st.stop()

    mejor = resultados[0]
    segundos = max(0, int(mejor["offset_frames"] * HOP / SR))  # segundo de la cancion donde empieza la grabacion

    st.success(f"**{mejor['name']}**")
    st.caption(f"Score: {mejor['score']} · tu fragmento empieza en el minuto {segundos // 60}:{segundos % 60:02d}")
    if mejor["source_url"]:
        st.video(mejor["source_url"], start_time=segundos)

    if len(resultados) > 1:
        with st.expander("Otras coincidencias"):
            for r in resultados[1:]:
                nombre = f"[{r['name']}]({r['source_url']})" if r["source_url"] else r["name"]
                st.markdown(f"- {nombre} (score {r['score']})")
