import os
import time
import hashlib
import stat
import unicodedata
from pathlib import Path
from typing import Optional, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
import pandas as pd
from tqdm import tqdm
import sys

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from training.paths import get_dataset_roots
from dataset_references import reference_from_path, resolve_reference
import soundfile as sf

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
    "file_path",
    "file_stage",
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
    *,
    roots: Dict[str, Path],
) -> Dict[str, Any]:
    """Emit raw references only for verified, nonempty physical originals."""
    reference = reference_from_path(file_path, "raw", roots)
    if file_path.stat().st_size == 0:
        raise ValueError("downloaded audio must be nonempty")
    if audio_info is None:
        audio_info = get_audio_info(file_path)

    file_size = file_path.stat().st_size
    file_hash = compute_file_sha256(file_path)

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
        **reference,
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


def _physical_path(value: Path) -> Path:
    """Preflight a future path without resolving away ancestor aliases."""
    text = str(value)
    if (not text.startswith("/") or "\\" in text or ":" in text
            or any(unicodedata.category(c) == "Cc" for c in text)
            or any(p in ("", ".", "..") for p in text[1:].split("/"))):
        raise ValueError("path must be canonical absolute POSIX text")
    path = Path(value)
    for entry in (path, *path.parents):
        try:
            mode = entry.lstat().st_mode
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError("path ancestors cannot be physically verified") from None
        if stat.S_ISLNK(mode) or (entry != path and not stat.S_ISDIR(mode)):
            raise ValueError("path ancestors must be physical directories without symlinks")
    return path


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

    dest_path = _physical_path(dest_path)
    if dest_path.exists():
        raise ValueError("download destination already exists")

    for attempt in range(max_retries):
        try:
            with session.get(url, stream=True, timeout=30) as r:
                if r.status_code != 200:
                    time.sleep(1)
                    continue
                content = b"".join(chunk for chunk in r.iter_content(chunk_size=chunk_size) if chunk)
            if not content:
                return False
            _physical_path(dest_path)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("xb") as f:
                f.write(content)
            return True
        except FileExistsError:
            raise ValueError("download destination already exists") from None
        except Exception:
            # Never adopt or remove a partially published original on retry.
            if dest_path.exists():
                return False
            time.sleep(1.5 * (attempt + 1))

    return False


def run_download_pipeline(
    data_dir: Optional[Path] = None,
    api_key: Optional[str] = None,
    species_list: Optional[List[tuple[str, str]]] = None,
    max_per_species: Optional[int] = None,
    *,
    metadata_index: Optional[Path] = None,
) -> pd.DataFrame:
    """Append verified raw rows progressively; not an atomic whole-batch publication.

    data_dir is the declared physical raw root, never inferred from an index.
    Legacy indexes require offline CANON-5 conversion before acquisition.
    """
    raw_dir = _physical_path(data_dir if data_dir is not None else get_dataset_roots("AvesChilenas")["raw"])
    metadata_file = _physical_path(metadata_index if metadata_index is not None else raw_dir / "metadata.csv")
    roots = {"raw": raw_dir}
    if raw_dir.exists() and not raw_dir.is_dir():
        raise ValueError("raw root must be a physical directory")
    if metadata_file.exists():
        if not metadata_file.is_file():
            raise ValueError("metadata index must be a regular file")
        existing_df = pd.read_csv(metadata_file, dtype=str, keep_default_na=False)
        if not {"file_path", "file_stage", "xc_id"}.issubset(existing_df.columns):
            raise ValueError("file_path and file_stage required; convert legacy index offline")
        for row in existing_df.to_dict("records"):
            source = resolve_reference(row["file_path"], row["file_stage"], roots)
            if source.samefile(metadata_file):
                raise ValueError("metadata index cannot be an audio source")
    else:
        existing_df = pd.DataFrame(columns=EXPECTED_COLUMNS)

    if api_key is None:
        api_key = os.getenv("XC_API_KEY")
        if not api_key:
            raise ValueError("XC_API_KEY required in environment or explicit argument")
    if species_list is None:
        species_list = APPROVED_SPECIES
    session = create_resilient_session()

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
        _physical_path(species_dir)

        to_process = []
        for rec in recs:
            xc_id = str(rec.get("id"))
            if xc_id in existing_xc_ids:
                continue
            file_url = rec.get("file")
            if not file_url:
                continue
            if (not xc_id or xc_id in (".", "..") or any(c in xc_id for c in "/\\:")
                    or any(unicodedata.category(c) == "Cc" for c in xc_id)):
                raise ValueError("recording identity must be a safe filename component")
            dest_file = _physical_path(species_dir / f"{xc_id}.mp3")
            if dest_file == metadata_file or dest_file.exists():
                raise ValueError("unindexed download destination already exists or overlaps index")
            existing_xc_ids.add(xc_id)
            to_process.append((rec, dest_file, file_url))

        if not to_process:
            print(f"  Todas las grabaciones de {common_name} ya están procesadas.")
            continue

        def _process_item(item):
            rec_item, d_file, f_url = item
            ok = download_file(f_url, d_file, session=session)
            if not ok:
                return None
            info = get_audio_info(d_file)
            return create_metadata_row(rec_item, d_file, clase=common_name, audio_info=info, roots=roots)

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
        current_df = pd.DataFrame(rows_list).reindex(columns=list(dict.fromkeys([*existing_df.columns, *EXPECTED_COLUMNS])))
        if species_added:
            _physical_path(metadata_file)
            metadata_file.parent.mkdir(parents=True, exist_ok=True)
            current_df.to_csv(metadata_file, index=False)
        print(f"  {species_added} nuevas grabaciones guardadas para {common_name}. Total acumulado: {len(current_df)}")

    final_df = pd.DataFrame(rows_list).reindex(columns=list(dict.fromkeys([*existing_df.columns, *EXPECTED_COLUMNS])))
    print(f"\nDescarga finalizada. Índice: {metadata_file} ({len(final_df)} filas; publicado solo si hubo éxitos nuevos).")
    return final_df


def main(argv=None):
    """CLI with physical Aves defaults and independent root/index overrides."""
    import argparse
    parser = argparse.ArgumentParser(description="Download canonical raw recordings")
    parser.add_argument("--raw-dir", "--data-dir", dest="raw_dir", type=Path)
    parser.add_argument("--metadata-index", type=Path)
    parser.add_argument("--max-per-species", type=int)
    args = parser.parse_args(argv)
    raw = args.raw_dir if args.raw_dir is not None else get_dataset_roots("AvesChilenas")["raw"]
    return run_download_pipeline(data_dir=raw, metadata_index=args.metadata_index,
                                 max_per_species=args.max_per_species)


if __name__ == "__main__":
    main()
