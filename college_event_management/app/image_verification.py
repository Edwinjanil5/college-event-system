"""Image similarity verification against a small set of campus reference images.

Design constraints
------------------
1. Five or fewer reference photographs cannot train a reliable
   college-specific classifier. This module therefore performs *visual
   comparison only*: it embeds an uploaded image and compares it with
   embeddings of the available reference images using cosine similarity.
2. Cosine similarity is NOT a probability and NOT proof that a photograph was
   taken at the college. The result is always reported with one of the
   indicative labels below.
3. The embedding backend is pluggable. The default ``perceptual`` backend uses
   only Pillow (already a dependency) so the module works offline with no
   large installs. The optional ``clip`` backend uses a pretrained CLIP model
   and is imported lazily; when its dependencies are absent the caller gets
   ``MODEL_UNAVAILABLE`` instead of a crash.
4. Reference embeddings are cached on disk, keyed by the image content hash
   and the backend version, so adding, removing or replacing a reference image
   never requires re-training anything.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from typing import Sequence

from PIL import Image, ImageFile, UnidentifiedImageError

# Pillow refuses to decode images with excessive pixel counts, which is a
# useful guard against decompression-bomb style uploads.
Image.MAX_IMAGE_PIXELS = 40_000_000
ImageFile.LOAD_TRUNCATED_IMAGES = False

POSSIBLE_VISUAL_MATCH = 'POSSIBLE_VISUAL_MATCH'
LOW_VISUAL_SIMILARITY = 'LOW_VISUAL_SIMILARITY'
INCONCLUSIVE = 'INCONCLUSIVE'
REFERENCE_IMAGES_UNAVAILABLE = 'REFERENCE_IMAGES_UNAVAILABLE'
MODEL_UNAVAILABLE = 'MODEL_UNAVAILABLE'
INVALID_IMAGE = 'INVALID_IMAGE'

ALLOWED_FORMATS = {'JPEG', 'PNG', 'WEBP', 'AVIF'}
SUPPORTED_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.avif'}

EMBEDDING_SIZE = 32


@dataclass
class ImageVerificationResult:
    """Indicative visual comparison outcome."""

    status: str
    similarity: float | None = None
    best_reference: str | None = None
    backend: str = ''
    reference_count: int = 0
    reference_images: list[str] = field(default_factory=list)
    reason: str = ''
    note: str = 'Visual similarity only; not proof of where a photo was taken.'

    @property
    def is_available(self) -> bool:
        return self.status in {POSSIBLE_VISUAL_MATCH, LOW_VISUAL_SIMILARITY}

    def as_dict(self) -> dict:
        return {
            'status': self.status,
            'similarity': round(self.similarity, 4) if self.similarity is not None else None,
            'best_reference': self.best_reference,
            'backend': self.backend,
            'reference_count': self.reference_count,
            'reason': self.reason,
            'note': self.note,
        }


class ImageRejected(ValueError):
    """Raised when an uploaded file cannot be decoded as a supported image."""


# ---------------------------------------------------------------------------
# Safe decoding
# ---------------------------------------------------------------------------
def decode_image(raw: bytes, max_bytes: int) -> Image.Image:
    """Decode and validate uploaded image bytes.

    The declared MIME type is never trusted; the bytes themselves are
    decoded and the real format is checked.
    """
    if not raw:
        raise ImageRejected('The uploaded file is empty.')
    if len(raw) > max_bytes:
        raise ImageRejected('The uploaded image is too large.')

    import io

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            image_format = (probe.format or '').upper()
            if image_format not in ALLOWED_FORMATS:
                raise ImageRejected(
                    f'Unsupported image format: {image_format or "unknown"}. '
                    f'Allowed: {", ".join(sorted(ALLOWED_FORMATS))}.'
                )
            probe.verify()  # validates the file structure without decoding pixels
        with Image.open(io.BytesIO(raw)) as decoded:
            decoded.load()
            return decoded.convert('RGB')
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise ImageRejected('The uploaded file is not a readable image.') from exc


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------
def _l2_normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def _zscore(values: list[float]) -> list[float]:
    """Centre and scale a vector; a constant vector yields all zeros."""
    count = len(values)
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / count
    std = variance ** 0.5
    if std < 1e-9:
        return [0.0] * count
    return [(value - mean) / std for value in values]


def image_contrast(image: Image.Image) -> float:
    """Standard deviation of luminance. Near zero means a featureless image."""
    thumbnail = image.convert('L').resize((64, 64), Image.BILINEAR)
    values = thumbnail.tobytes()
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5


def is_degenerate(image: Image.Image, threshold: float = 3.0) -> bool:
    """True for blank or near-blank images, which carry no visual evidence."""
    return image_contrast(image) < threshold


def perceptual_embedding(image: Image.Image) -> list[float]:
    """Deterministic low-level fingerprint computed with Pillow only.

    Every feature block is standardised against its own statistics, so the
    embedding describes layout and contrast structure rather than overall
    brightness. Without this a flat grey image and a real photograph both
    normalise to near-identical vectors, and the comparison stops
    discriminating between them.

    Blocks: contrast-normalised grayscale thumbnail, horizontal gradients,
    row profile, column profile and colour balance.
    """
    thumbnail = image.convert('L').resize((EMBEDDING_SIZE, EMBEDDING_SIZE), Image.BILINEAR)
    grayscale = [float(value) for value in thumbnail.tobytes()]
    normalised = _zscore(grayscale)

    gradients: list[float] = []
    for row in range(EMBEDDING_SIZE):
        offset = row * EMBEDDING_SIZE
        for column in range(EMBEDDING_SIZE - 1):
            gradients.append(normalised[offset + column + 1] - normalised[offset + column])

    row_profile: list[float] = []
    column_profile: list[float] = []
    for index in range(EMBEDDING_SIZE):
        offset = index * EMBEDDING_SIZE
        row_profile.append(sum(grayscale[offset : offset + EMBEDDING_SIZE]) / EMBEDDING_SIZE)
        column_profile.append(sum(grayscale[index::EMBEDDING_SIZE]) / EMBEDDING_SIZE)

    # Colour balance relative to overall brightness keeps hue information while
    # discarding how bright the scene was.
    channels = image.split()[:3]
    channel_means = []
    for channel in channels:
        data = channel.resize((16, 16), Image.BILINEAR).tobytes()
        channel_means.append(sum(data) / len(data))
    luma = sum(channel_means) / len(channel_means)
    colour_balance = _zscore([mean - luma for mean in channel_means])

    vector = normalised + gradients + _zscore(row_profile) + _zscore(column_profile) + colour_balance
    return _l2_normalise(vector)


class ClipEmbedding:
    """Optional CLIP backend.

    Imported lazily so the application runs without PyTorch installed. Callers
    use :func:`build_embedding_backend` and handle ``MODEL_UNAVAILABLE``.
    """

    name = 'clip'
    version = 'clip-vit-b32'

    def __init__(self, model_name: str = 'ViT-B-32', pretrained: str = 'openai'):
        import open_clip  # noqa: F401  (import failure is handled by the caller)
        import torch

        self._torch = torch
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained
        )
        self._model.eval()
        self._tokenizer = open_clip.get_tokenizer(model_name)

    def available(self) -> bool:
        return True

    def embed(self, image: Image.Image) -> list[float]:
        torch = self._torch
        tensor = self._preprocess(image).unsqueeze(0)
        with torch.no_grad():
            features = self._model.encode_image(tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return [float(value) for value in features[0].tolist()]


class PerceptualEmbedding:
    """Default zero-dependency backend."""

    name = 'perceptual'
    version = 'perceptual-v1'

    def available(self) -> bool:
        return True

    def embed(self, image: Image.Image) -> list[float]:
        return perceptual_embedding(image)


def build_embedding_backend(name: str):
    """Return an embedding backend, or ``None`` when it is unavailable."""
    if name == ClipEmbedding.name:
        try:
            return ClipEmbedding()
        except Exception:  # pragma: no cover - depends on optional dependency
            return None
    return PerceptualEmbedding()


# ---------------------------------------------------------------------------
# Reference index with on-disk embedding cache
# ---------------------------------------------------------------------------
class ReferenceIndex:
    """Embeddings for the configured campus reference images.

    Similarity is plain cosine on contrast-normalised embeddings. Whitening
    against per-column reference statistics was implemented and then removed:
    with only a handful of references those statistics come from too few
    samples and amplify JPEG artefacts (measured on an identical scene -
    similarity 1.00 at JPEG quality 90 but 0.12 at quality 85). Contrast
    normalisation lives inside the embedding instead, which is stable at this
    sample size.
    """

    def __init__(self, backend, entries: list[dict], version: str):
        self.backend = backend
        self.version = version
        self.entries = entries

    @property
    def names(self) -> list[str]:
        return [entry['name'] for entry in self.entries]

    def __len__(self) -> int:
        return len(self.entries)

    def best_match(self, vector: Sequence[float]) -> tuple[str | None, float | None]:
        if not self.entries:
            return None, None
        best_name = None
        best_score = None
        for entry in self.entries:
            score = cosine_similarity(vector, entry['vector'])
            if best_score is None or score > best_score:
                best_score = score
                best_name = entry['name']
        return best_name, best_score


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _file_digest(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def list_reference_images(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    names = []
    for name in sorted(os.listdir(folder)):
        if os.path.splitext(name)[1].lower() in SUPPORTED_SUFFIXES:
            if os.path.isfile(os.path.join(folder, name)):
                names.append(name)
    return names


def _load_cache(cache_path: str) -> dict:
    if not cache_path or not os.path.isfile(cache_path):
        return {}
    try:
        with open(cache_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _store_cache(cache_path: str, payload: dict) -> None:
    if not cache_path:
        return
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        tmp_path = cache_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)
        os.replace(tmp_path, cache_path)
    except OSError:
        pass  # cache is an optimisation, never a requirement


def build_reference_index(
    folder: str,
    backend,
    cache_path: str = '',
    max_bytes: int = 10 * 1024 * 1024,
) -> ReferenceIndex:
    """Embed every reference image, reusing cached vectors where possible."""
    cache = _load_cache(cache_path)
    backend_key = f'{backend.name}:{backend.version}'
    cached_entries = cache.get(backend_key, {})
    if not isinstance(cached_entries, dict):
        cached_entries = {}

    entries: list[dict] = []
    fresh: dict[str, dict] = {}
    for name in list_reference_images(folder):
        path = os.path.join(folder, name)
        try:
            digest = _file_digest(path)
        except OSError:
            continue
        cached = cached_entries.get(digest)
        if cached and isinstance(cached.get('vector'), list) and cached.get('name') == name:
            entries.append(cached)
            continue
        try:
            with open(path, 'rb') as handle:
                raw = handle.read()
            image = decode_image(raw, max_bytes)
            vector = backend.embed(image)
        except (ImageRejected, OSError, ValueError):
            # A corrupt reference image is skipped, not fatal.
            continue
        entry = {'name': name, 'digest': digest, 'vector': vector}
        entries.append(entry)
        fresh[digest] = entry

    if cache_path:
        merged = dict(cached_entries)
        # Drop cache entries whose source file no longer exists.
        live = {entry['digest'] for entry in entries}
        for digest in list(merged):
            if digest not in live:
                del merged[digest]
        merged.update(fresh)
        _store_cache(cache_path, {backend_key: merged})

    return ReferenceIndex(backend, entries, backend.version)


# ---------------------------------------------------------------------------
# Verification entry point
# ---------------------------------------------------------------------------
def verify_image_against_references(
    raw: bytes | None,
    index: ReferenceIndex | None,
    backend_name: str,
    max_bytes: int,
    similarity_threshold: float,
) -> ImageVerificationResult:
    """Compare an uploaded image with the campus reference images.

    The returned status is indicative only. A low similarity never means the
    photo was not taken at the college: lighting, weather, cropping and camera
    settings all change the fingerprint.
    """
    if index is None:
        return ImageVerificationResult(
            status=MODEL_UNAVAILABLE,
            backend=backend_name,
            reason='The image comparison backend could not be loaded.',
        )

    if len(index) == 0:
        return ImageVerificationResult(
            status=REFERENCE_IMAGES_UNAVAILABLE,
            backend=backend_name,
            reference_count=0,
            reason='No campus reference images are configured yet.',
        )

    if raw is None:
        return ImageVerificationResult(
            status=INCONCLUSIVE,
            backend=backend_name,
            reference_count=len(index),
            reference_images=index.names,
            reason='No photo was submitted, so there was nothing to compare.',
        )

    try:
        image = decode_image(raw, max_bytes)
    except ImageRejected as exc:
        return ImageVerificationResult(
            status=INVALID_IMAGE,
            backend=backend_name,
            reference_count=len(index),
            reference_images=index.names,
            reason=str(exc),
        )

    if is_degenerate(image):
        # A blank or flat image carries no visual evidence; scoring it would
        # only produce a meaningless number.
        return ImageVerificationResult(
            status=INCONCLUSIVE,
            backend=backend_name,
            reference_count=len(index),
            reference_images=index.names,
            reason='The uploaded image is too uniform to compare visually.',
        )

    try:
        vector = index.backend.embed(image)
    except Exception as exc:  # pragma: no cover - defensive
        return ImageVerificationResult(
            status=MODEL_UNAVAILABLE,
            backend=backend_name,
            reference_count=len(index),
            reference_images=index.names,
            reason=f'Image comparison failed: {exc.__class__.__name__}.',
        )

    best_name, best_score = index.best_match(vector)
    if best_score is None:
        return ImageVerificationResult(
            status=INCONCLUSIVE,
            backend=backend_name,
            reference_count=len(index),
            reference_images=index.names,
            reason='No comparison could be produced.',
        )

    status = (
        POSSIBLE_VISUAL_MATCH
        if best_score >= similarity_threshold
        else LOW_VISUAL_SIMILARITY
    )
    return ImageVerificationResult(
        status=status,
        similarity=best_score,
        best_reference=best_name,
        backend=backend_name,
        reference_count=len(index),
        reference_images=index.names,
        reason='',
    )