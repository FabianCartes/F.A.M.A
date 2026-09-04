import os
import time
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import pandas as pd
from tqdm import tqdm
import soundfile as sf
import dotenv

EXPECTED_COLUMNS = [
    "nombre_archivo",
    "clase",
    "frecuencia_muestreo",
    "duracion_segundos",
    "tamano_bytes",
    "hash_archivo",
    "xc_id",
    "recordist",
    "licencia",
    "pais",
    "localidad",
    "lat",
    "lon",
    "calidad",
]

# Top 15 approved species for F.A.M.A. PoC
APPROVED_SPECIES: List[tuple[str, str]] = [
    ("Zorzal patagónico", "Turdus falcklandii"),
    ("Rayadito", "Aphrastura spinicauda"),
    ("Chucao", "Scelorchilus rubecula"),
    ("Chercán", "Troglodytes aedon"),
    ("Tordo", "Curaeus curaeus"),
    ("Turca", "Pteroptochos megapodius"),
    ("Fío-fío", "Elaenia chilensis"),
    ("Chincol", "Zonotrichia capensis"),
    ("Churrín de la Mocha", "Eugralla paradoxa"),
    ("Churrín del sur", "Scytalopus magellanicus"),
    ("Picaflor chico", "Sephanoides sephaniodes"),
    ("Canastero", "Pseudasthenes humicola"),
    ("Tijeral", "Leptasthenura aegithaloides"),
    ("Tapaculo", "Scelorchilus albicollis"),
    ("Colilarga", "Sylviorthorhynchus desmurii"),
]


def create_resilient_session() -> requests.Session:
    """Crea una sesión HTTP con reintentos automáticos y backoff exponencial."""
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def compute_file_sha256(file_path: Path) -> str:
    """Calcula el hash SHA-256 de un archivo binario."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_audio_info(file_path: Path) -> Dict[str, Any]:
    """Extrae samplerate y duración en segundos usando soundfile."""
    try:
        info = sf.info(str(file_path))
        return {
            "frecuencia_muestreo": int(info.samplerate),
            "duracion_segundos": round(float(info.duration), 3),
        }
    except Exception:
        return {
            "frecuencia_muestreo": None,
            "duracion_segundos": None,
        }


def create_metadata_row(
    rec: Dict[str, Any],
    file_path: Path,
    clase: str,
    audio_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Genera un diccionario con las columnas exactas de la tabla audio."""
    if audio_info is None:
        audio_info = get_audio_info(file_path)

    file_size = file_path.stat().st_size if file_path.exists() else 0
    file_hash = compute_file_sha256(file_path) if file_path.exists() else ""

    lat = rec.get("lat")
    lon = rec.get("lng") if "lng" in rec else rec.get("lon")

    return {
        "nombre_archivo": file_path.name,
        "clase": clase,
        "frecuencia_muestreo": audio_info.get("frecuencia_muestreo"),
        "duracion_segundos": audio_info.get("duracion_segundos"),
        "tamano_bytes": file_size,
        "hash_archivo": file_hash,
        "xc_id": str(rec.get("id", "")),
        "recordist": rec.get("rec", ""),
        "licencia": rec.get("lic", ""),
        "pais": rec.get("cnt", ""),
        "localidad": rec.get("loc", ""),
        "lat": lat,
        "lon": lon,
        "calidad": rec.get("q", ""),
    }


def search_recordings(
    species_sci: str,
    api_key: str,
    country: str = "Chile",
    qualities: Optional[List[str]] = None,
    session: Optional[requests.Session] = None,
    max_retries: int = 4,
) -> List[Dict[str, Any]]:
    """Consulta la API v3 de Xeno-canto con paginación y reintentos ante desconexión."""
    if session is None:
        session = create_resilient_session()

    if qualities is None:
        qualities = ["A", "B"]

    all_recordings: List[Dict[str, Any]] = []

    for q in qualities:
        page = 1
        query = f'sp:"{species_sci}" cnt:{country} q:{q}'
        while True:
            url = f"https://xeno-canto.org/api/3/recordings?query={query}&page={page}&key={api_key}"
            success = False
            for attempt in range(max_retries):
                try:
                    resp = session.get(url, timeout=25)
                    if resp.status_code == 200:
                        data = resp.json()
                        recs = data.get("recordings", [])
                        all_recordings.extend(recs)
                        num_pages = int(data.get("numPages", 1))
                        success = True
                        break
                    elif resp.status_code == 429:
                        time.sleep(3 * (attempt + 1))
                    else:
                        time.sleep(1)
                except Exception as e:
                    time.sleep(2 * (attempt + 1))

            if not success or page >= num_pages:
                break
            page += 1
            time.sleep(0.15)

    seen_ids = set()
    unique_recordings = []
    for r in all_recordings:
        rid = r.get("id")
        if rid and rid not in seen_ids:
            seen_ids.add(rid)
            unique_recordings.append(r)

    return unique_recordings


def download_file(
    url: str,
    dest_path: Path,
    session: Optional[requests.Session] = None,
    chunk_size: int = 65536,
    max_retries: int = 3,
) -> bool:
    """Descarga un archivo con reintentos y soporte de esquemas relativos."""
    if session is None:
        session = create_resilient_session()

    if url.startswith("//"):
        url = "https:" + url

    dest_path.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(max_retries):
        try:
            with session.get(url, stream=True, timeout=30) as r:
                if r.status_code != 200:
                    time.sleep(1)
                    continue
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
            if dest_path.exists() and dest_path.stat().st_size > 0:
                return True
        except Exception:
            if dest_path.exists():
                try:
                    dest_path.unlink()
                except Exception:
                    pass
            time.sleep(1.5 * (attempt + 1))

    return False


def run_download_pipeline(
    data_dir: Path,
    api_key: Optional[str] = None,
    species_list: Optional[List[tuple[str, str]]] = None,
    max_per_species: Optional[int] = None,
) -> pd.DataFrame:
    """Ejecuta la descarga masiva y persistencia continua de data/metadata.csv."""
    if api_key is None:
        dotenv.load_dotenv()
        api_key = os.getenv("XC_API_KEY")
        if not api_key:
            raise ValueError("XC_API_KEY no encontrada en entorno ni en .env")

    if species_list is None:
        species_list = APPROVED_SPECIES

    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = data_dir / "metadata.csv"

    session = create_resilient_session()

    if metadata_file.exists():
        existing_df = pd.read_csv(metadata_file)
    else:
        existing_df = pd.DataFrame(columns=EXPECTED_COLUMNS)

    existing_xc_ids = set(existing_df["xc_id"].astype(str).tolist()) if not existing_df.empty else set()
    rows_list = existing_df.to_dict("records") if not existing_df.empty else []

    print(f"\nIniciando adquisición para {len(species_list)} especies...")

    for common_name, sci_name in species_list:
        print(f"\nBuscando grabaciones para: {common_name} ({sci_name})")
        recs = search_recordings(sci_name, api_key=api_key, country="Chile", session=session)
        if max_per_species:
            recs = recs[:max_per_species]

        print(f"  Encontradas {len(recs)} grabaciones A/B en Xeno-canto.")
        species_slug = common_name.lower().replace(" ", "_").replace("/", "_")
        species_dir = raw_dir / species_slug
        species_dir.mkdir(parents=True, exist_ok=True)

        to_process = []
        for rec in recs:
            xc_id = str(rec.get("id"))
            if xc_id in existing_xc_ids:
                continue
            file_url = rec.get("file")
            if not file_url:
                continue
            dest_file = species_dir / f"{xc_id}.mp3"
            to_process.append((rec, dest_file, file_url))

        if not to_process:
            print(f"  Todas las grabaciones de {common_name} ya están procesadas.")
            continue

        def _process_item(item):
            rec_item, d_file, f_url = item
            if not d_file.exists() or d_file.stat().st_size == 0:
                ok = download_file(f_url, d_file, session=session)
                if not ok:
                    return None
            info = get_audio_info(d_file)
            return create_metadata_row(rec_item, d_file, clase=common_name, audio_info=info)

        species_added = 0
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_process_item, item) for item in to_process]
            for f in tqdm(as_completed(futures), total=len(futures), desc=f"Descargando {common_name}"):
                res = f.result()
                if res is not None:
                    rows_list.append(res)
                    existing_xc_ids.add(res["xc_id"])
                    species_added += 1

        # Guardar progreso tras cada especie para no perder nada si hay corte
        current_df = pd.DataFrame(rows_list)
        current_df.to_csv(metadata_file, index=False)
        print(f"  {species_added} nuevas grabaciones guardadas para {common_name}. Total acumulado: {len(current_df)}")

    final_df = pd.DataFrame(rows_list)
    final_df.to_csv(metadata_file, index=False)
    print(f"\nDescarga finalizada. Metadatos persistidos en {metadata_file} ({len(final_df)} filas totales).")
    return final_df


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent.parent
    data_directory = project_root / "data"
    run_download_pipeline(data_dir=data_directory)
