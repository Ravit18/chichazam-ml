# Este script sube fingerprints.db a Hugging Face para que la app de Streamlit la descargue al arrancar
# (pesa demasiado para GitHub). Volver a correrlo cada vez que se agreguen canciones a la BD.
# Flujo: copia compacta de la BD (sin el indice por cancion, que la app no usa) -> subirla al repo.
import os
import sqlite3
import tempfile
from pathlib import Path
from dotenv import load_dotenv
from huggingface_hub import create_repo, upload_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "fingerprints.db"

HF_REPO_ID = "pollitoconpapass/chichazam-fingerprints"
REPO_TYPE = "dataset"

load_dotenv(PROJECT_ROOT / ".env")
HF_TOKEN = os.getenv("HF_TOKEN")  # si no hay, se usa la sesion de `hf auth login`


def export_compact(src: Path, dst: Path) -> None:
    conn = sqlite3.connect(dst)
    conn.executescript("""
        CREATE TABLE songs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            n_hashes   INTEGER NOT NULL DEFAULT 0,
            source_url TEXT
        );
        CREATE TABLE fingerprints (
            hash         INTEGER NOT NULL,
            song_id      INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
            anchor_time  INTEGER NOT NULL,
            PRIMARY KEY (hash, song_id, anchor_time)
        ) WITHOUT ROWID;
    """)
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("ATTACH DATABASE ? AS src", (str(src),))
    with conn:
        conn.execute("INSERT INTO songs SELECT id, name, n_hashes, source_url FROM src.songs")
        conn.execute("INSERT INTO fingerprints SELECT hash, song_id, anchor_time FROM src.fingerprints ORDER BY hash, song_id, anchor_time")
    conn.execute("DETACH DATABASE src")
    conn.close()


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="fingerprints_") as tmp:
        compact = Path(tmp) / "fingerprints.db"
        print("Generando copia compacta de la BD...")
        export_compact(DB_PATH, compact)
        print(f"Original: {DB_PATH.stat().st_size / 1e6:.0f} MB | Compacta: {compact.stat().st_size / 1e6:.0f} MB")

        create_repo(HF_REPO_ID, repo_type=REPO_TYPE, token=HF_TOKEN, exist_ok=True)
        upload_file(
            path_or_fileobj=str(compact),
            path_in_repo="fingerprints.db",
            repo_id=HF_REPO_ID,
            repo_type=REPO_TYPE,
            token=HF_TOKEN,
        )
    print(f"Listo: https://huggingface.co/datasets/{HF_REPO_ID}")


if __name__ == "__main__":
    main()
