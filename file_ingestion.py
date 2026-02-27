#!/usr/bin/env python3
"""
File Ingestion pour ACP Agents
Pipeline: upload base64 → extraction texte → chunking → indexation vectorielle
Supporte PDF, DOCX, TXT, MD.
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
import zipfile
from io import BytesIO
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("file-ingestion")

# Constantes
MAX_FILE_SIZE = 32 * 1024 * 1024  # 32 MB
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
BLOB_DIR = os.path.join(UPLOAD_DIR, "blobs")
TEXT_DIR = os.path.join(UPLOAD_DIR, "texts")
MANIFEST_PATH = os.path.join(UPLOAD_DIR, "manifest.json")
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
MAX_FILES = 500


def ensure_dirs():
    """Créer les répertoires nécessaires."""
    os.makedirs(BLOB_DIR, exist_ok=True)
    os.makedirs(TEXT_DIR, exist_ok=True)


def load_manifest() -> Dict:
    """Charger le manifeste des fichiers uploadés."""
    if os.path.exists(MANIFEST_PATH):
        try:
            with open(MANIFEST_PATH, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {"files": []}
    return {"files": []}


def save_manifest(manifest: Dict):
    """Sauvegarder le manifeste atomiquement."""
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, 'w') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def validate_filename(filename: str) -> Tuple[bool, str]:
    """Valider un nom de fichier (sécurité)."""
    if not filename or len(filename) > 255:
        return False, "Nom de fichier invalide"
    if '..' in filename or '/' in filename or '\\' in filename:
        return False, "Path traversal bloqué"
    _, ext = os.path.splitext(filename.lower())
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extension non supportée: {ext}. Autorisées: {ALLOWED_EXTENSIONS}"
    return True, ""


def extract_text_pdf(data: bytes) -> str:
    """Extraire le texte d'un PDF — regex basique + fallback pdftotext."""
    text_parts = []

    # Méthode 1 : regex basique sur les streams PDF
    try:
        content = data.decode('latin-1')
        for match in re.finditer(r'\((.*?)\)', content):
            txt = match.group(1)
            if len(txt) > 2 and any(c.isalpha() for c in txt):
                text_parts.append(txt)
    except Exception:
        pass

    # Méthode 2 : pdftotext si disponible (meilleur)
    if not text_parts or len(" ".join(text_parts)) < 100:
        try:
            import subprocess
            result = subprocess.run(
                ['pdftotext', '-', '-'],
                input=data, capture_output=True, timeout=30
            )
            if result.returncode == 0:
                extracted = result.stdout.decode('utf-8', errors='replace')
                if len(extracted) > len(" ".join(text_parts)):
                    text_parts = [extracted]
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    return "\n".join(text_parts)


MAX_DOCX_DECOMPRESSED = 50 * 1024 * 1024  # 50 MB max décompressé (anti zip bomb)

def extract_text_docx(data: bytes) -> str:
    """Extraire le texte d'un DOCX (ZIP + XML). Protégé contre zip bombs."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = zf.namelist()
            if 'word/document.xml' not in names:
                return ""
            # Protection zip bomb : vérifier la taille décompressée
            info = zf.getinfo('word/document.xml')
            if info.file_size > MAX_DOCX_DECOMPRESSED:
                logger.warning(f"DOCX zip bomb détecté: {info.file_size} bytes décompressés")
                return ""
            xml_content = zf.read('word/document.xml').decode('utf-8', errors='replace')
            texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml_content)
            return " ".join(texts)
    except (zipfile.BadZipFile, KeyError, Exception) as e:
        logger.error(f"Erreur extraction DOCX: {e}")
        return ""


def extract_text(data: bytes, extension: str) -> str:
    """Router l'extraction selon le type de fichier."""
    if extension in ('.txt', '.md'):
        return data.decode('utf-8', errors='replace')
    elif extension == '.pdf':
        return extract_text_pdf(data)
    elif extension == '.docx':
        return extract_text_docx(data)
    return ""


def chunk_text_for_indexing(text: str) -> List[str]:
    """Découper le texte en chunks pour indexation vectorielle."""
    if not text:
        return []
    chunks = []
    step = max(CHUNK_SIZE - CHUNK_OVERLAP, 1)
    for i in range(0, len(text), step):
        chunk = text[i:i + CHUNK_SIZE]
        if chunk.strip():
            chunks.append(chunk)
    return chunks


class FileIngestion:
    """Gestionnaire d'ingestion de fichiers."""

    def __init__(self, vector_store=None):
        self.vector_store = vector_store
        ensure_dirs()
        self.manifest = load_manifest()

    async def upload(self, filename: str, content_b64: str,
                     metadata: Optional[Dict] = None) -> Dict:
        """Uploader un fichier (base64) → extraire → chunker → indexer."""
        valid, err = validate_filename(filename)
        if not valid:
            return {"error": err}

        if len(self.manifest.get("files", [])) >= MAX_FILES:
            return {"error": f"Limite de {MAX_FILES} fichiers atteinte"}

        try:
            data = base64.b64decode(content_b64)
        except Exception:
            return {"error": "Contenu base64 invalide"}

        if len(data) > MAX_FILE_SIZE:
            return {"error": f"Fichier trop gros: {len(data)} bytes (max {MAX_FILE_SIZE})"}

        _, ext = os.path.splitext(filename.lower())
        file_id = hashlib.sha256(data).hexdigest()[:16]

        # Sauvegarder le blob
        blob_path = os.path.join(BLOB_DIR, f"{file_id}{ext}")
        if not os.path.realpath(blob_path).startswith(os.path.realpath(BLOB_DIR)):
            return {"error": "Path traversal bloqué"}
        with open(blob_path, 'wb') as f:
            f.write(data)

        # Extraire le texte
        text = extract_text(data, ext)
        text_path = os.path.join(TEXT_DIR, f"{file_id}.txt")
        with open(text_path, 'w') as f:
            f.write(text)

        # Indexer dans le vector store
        chunks_indexed = 0
        if self.vector_store and text:
            chunks = chunk_text_for_indexing(text)
            for i, chunk in enumerate(chunks):
                await self.vector_store.index(
                    chunk,
                    metadata={
                        "source": "file",
                        "file_id": file_id,
                        "filename": filename,
                        "chunk_index": i,
                        **(metadata or {})
                    }
                )
                chunks_indexed += 1

        # Mettre à jour le manifeste
        entry = {
            "id": file_id,
            "filename": filename,
            "extension": ext,
            "size_bytes": len(data),
            "text_length": len(text),
            "chunks_indexed": chunks_indexed,
            "uploaded_at": time.time(),
            "metadata": metadata or {}
        }
        self.manifest.setdefault("files", []).append(entry)
        save_manifest(self.manifest)

        return {
            "id": file_id,
            "filename": filename,
            "size_bytes": len(data),
            "text_extracted": len(text),
            "chunks_indexed": chunks_indexed,
            "status": "indexed"
        }

    def list_files(self) -> List[Dict]:
        """Lister tous les fichiers uploadés."""
        return [
            {
                "id": f["id"],
                "filename": f["filename"],
                "size_bytes": f["size_bytes"],
                "text_length": f["text_length"],
                "chunks_indexed": f["chunks_indexed"],
                "uploaded_at": f["uploaded_at"]
            }
            for f in self.manifest.get("files", [])
        ]

    def get_file(self, file_id: str) -> Optional[Dict]:
        """Récupérer les détails d'un fichier."""
        for f in self.manifest.get("files", []):
            if f["id"] == file_id:
                text_path = os.path.join(TEXT_DIR, f"{file_id}.txt")
                text = ""
                if os.path.exists(text_path):
                    safe_path = os.path.realpath(text_path)
                    if safe_path.startswith(os.path.realpath(TEXT_DIR)):
                        with open(text_path, 'r') as fh:
                            text = fh.read()
                return {**f, "text": text[:5000]}
        return None
