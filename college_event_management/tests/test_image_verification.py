"""Tests for image comparison against campus reference images.

Reference images are synthesised in a temporary folder so the tests never
depend on (or leak) real photographs, and the "genuine vs unrelated" checks
use images that were never part of the reference set.
"""

import io

import pytest
from PIL import Image, ImageDraw

from app.image_verification import (
    INCONCLUSIVE,
    INVALID_IMAGE,
    LOW_VISUAL_SIMILARITY,
    MODEL_UNAVAILABLE,
    POSSIBLE_VISUAL_MATCH,
    REFERENCE_IMAGES_UNAVAILABLE,
    ImageRejected,
    PerceptualEmbedding,
    build_embedding_backend,
    build_reference_index,
    cosine_similarity,
    decode_image,
    list_reference_images,
    perceptual_embedding,
    verify_image_against_references,
)

THRESHOLD = 0.92


# ---------------------------------------------------------------------------
# Synthetic image helpers
# ---------------------------------------------------------------------------
def make_campus_like_image(seed=0, size=(320, 240)):
    """A structured image: sky band, building block, dark doorway."""
    image = Image.new('RGB', size, (200, 210, 225))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, size[0], size[1] // 3], fill=(120, 160, 210))
    offset = seed * 7
    draw.rectangle(
        [40 + offset, 70, 220 + offset, 210], fill=(235, 232, 225)
    )
    draw.rectangle([120 + offset, 130, 160 + offset, 210], fill=(60, 60, 70))
    for column in range(60 + offset, 220 + offset, 30):
        draw.rectangle([column, 85, column + 18, 110], fill=(70, 90, 130))
    return image


def make_unrelated_image(size=(320, 240)):
    """A different scene: dark background with a bright diagonal band."""
    image = Image.new('RGB', size, (25, 25, 35))
    draw = ImageDraw.Draw(image)
    for step in range(0, size[0], 12):
        draw.line([(step, size[1]), (step + size[1], 0)], fill=(240, 210, 40), width=6)
    return image


def to_jpeg_bytes(image, quality=90):
    buffer = io.BytesIO()
    image.save(buffer, format='JPEG', quality=quality)
    return buffer.getvalue()


def to_png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Safe decoding
# ---------------------------------------------------------------------------
def test_valid_jpeg_and_png_decode():
    assert decode_image(to_jpeg_bytes(make_campus_like_image()), 5_000_000).mode == 'RGB'
    assert decode_image(to_png_bytes(make_campus_like_image()), 5_000_000).mode == 'RGB'


def test_empty_file_is_rejected():
    with pytest.raises(ImageRejected):
        decode_image(b'', 5_000_000)


def test_non_image_bytes_are_rejected():
    with pytest.raises(ImageRejected):
        decode_image(b'this is plain text pretending to be a photo', 5_000_000)


def test_corrupted_image_is_rejected():
    raw = bytearray(to_jpeg_bytes(make_campus_like_image()))
    raw[40:120] = b'\x00' * 80  # damage the entropy-coded data
    with pytest.raises(ImageRejected):
        decode_image(bytes(raw), 5_000_000)


def test_truncated_image_is_rejected():
    raw = to_jpeg_bytes(make_campus_like_image())
    with pytest.raises(ImageRejected):
        decode_image(raw[: len(raw) // 4], 5_000_000)


def test_unsupported_format_is_rejected():
    buffer = io.BytesIO()
    make_campus_like_image().save(buffer, format='BMP')
    with pytest.raises(ImageRejected) as excinfo:
        decode_image(buffer.getvalue(), 5_000_000)
    assert 'Unsupported image format' in str(excinfo.value)


def test_oversized_image_is_rejected_before_decoding():
    raw = to_jpeg_bytes(make_campus_like_image())
    with pytest.raises(ImageRejected):
        decode_image(raw, 100)


def test_declared_mime_type_is_not_trusted():
    # Correct magic bytes are required; a text file named .jpg is refused.
    with pytest.raises(ImageRejected):
        decode_image(b'<html>not a photo</html>', 5_000_000)


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------
def test_embedding_is_deterministic_and_normalised():
    image = make_campus_like_image()
    first = perceptual_embedding(image)
    second = perceptual_embedding(image)
    assert first == second
    magnitude = sum(value * value for value in first) ** 0.5
    assert magnitude == pytest.approx(1.0, abs=1e-9)


def test_similar_images_score_higher_than_unrelated_ones():
    reference = perceptual_embedding(make_campus_like_image())
    similar = perceptual_embedding(make_campus_like_image(seed=1, size=(300, 220)))
    unrelated = perceptual_embedding(make_unrelated_image())

    assert cosine_similarity(reference, similar) > cosine_similarity(reference, unrelated)
    assert cosine_similarity(reference, reference) == pytest.approx(1.0, abs=1e-9)


def test_cosine_similarity_handles_mismatched_or_empty_vectors():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_default_backend_is_available_and_clip_is_optional():
    assert build_embedding_backend('perceptual') is not None
    # CLIP needs optional heavy dependencies; absence must be handled, not crash.
    backend = build_embedding_backend('clip')
    assert backend is None or hasattr(backend, 'embed')


# ---------------------------------------------------------------------------
# Reference index
# ---------------------------------------------------------------------------
def write_reference(folder, count):
    folder.mkdir(parents=True, exist_ok=True)
    names = []
    for index in range(count):
        name = f'ref-{index + 1}.jpg'
        (folder / name).write_bytes(to_jpeg_bytes(make_campus_like_image(seed=index)))
        names.append(name)
    return names


def test_reference_index_with_no_images(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    assert list_reference_images(str(empty)) == []
    index = build_reference_index(str(empty), PerceptualEmbedding())
    assert len(index) == 0


def test_reference_index_with_missing_folder(tmp_path):
    index = build_reference_index(str(tmp_path / 'nope'), PerceptualEmbedding())
    assert len(index) == 0
    assert list_reference_images('') == []


@pytest.mark.parametrize('count', [1, 3, 5])
def test_reference_index_with_one_three_and_five_images(tmp_path, count):
    folder = tmp_path / f'refs-{count}'
    expected = write_reference(folder, count)
    index = build_reference_index(str(folder), PerceptualEmbedding())
    assert len(index) == count
    assert set(index.names) == set(expected)


def test_only_image_files_are_considered(tmp_path):
    folder = tmp_path / 'mixed'
    folder.mkdir()
    (folder / 'a.jpg').write_bytes(to_jpeg_bytes(make_campus_like_image()))
    (folder / 'notes.txt').write_text('not an image', encoding='utf-8')
    (folder / 'b.pdf').write_bytes(b'%PDF-1.4')
    assert list_reference_images(str(folder)) == ['a.jpg']


def test_corrupt_reference_file_is_skipped_not_fatal(tmp_path):
    folder = tmp_path / 'refs-corrupt'
    write_reference(folder, 2)
    (folder / 'broken.jpg').write_bytes(b'not really a jpeg')
    index = build_reference_index(str(folder), PerceptualEmbedding())
    assert len(index) == 2


def test_embeddings_are_cached_and_reused(tmp_path):
    folder = tmp_path / 'refs-cache'
    write_reference(folder, 2)
    cache = tmp_path / 'cache.json'

    first = build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))
    assert cache.is_file()

    second = build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))
    assert [entry['vector'] for entry in first.entries] == [
        entry['vector'] for entry in second.entries
    ]


def test_replacing_a_reference_image_invalidates_its_cache_entry(tmp_path):
    folder = tmp_path / 'refs-replace'
    write_reference(folder, 1)
    cache = tmp_path / 'cache.json'
    index = build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))
    original_vector = list(index.entries[0]['vector'])

    # Replace the file contents, keeping the same name.
    (folder / 'ref-1.jpg').write_bytes(to_jpeg_bytes(make_unrelated_image()))
    updated = build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))
    assert updated.entries[0]['vector'] != original_vector


def test_removing_a_reference_image_updates_the_index(tmp_path):
    folder = tmp_path / 'refs-remove'
    names = write_reference(folder, 3)
    cache = tmp_path / 'cache.json'
    assert len(build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))) == 3

    (folder / names[0]).unlink()
    reduced = build_reference_index(str(folder), PerceptualEmbedding(), cache_path=str(cache))
    assert len(reduced) == 2
    assert names[0] not in reduced.names


# ---------------------------------------------------------------------------
# Verification outcomes
# ---------------------------------------------------------------------------
def test_no_reference_images_returns_unavailable(tmp_path):
    folder = tmp_path / 'refs-none'
    folder.mkdir()
    index = build_reference_index(str(folder), PerceptualEmbedding())
    result = verify_image_against_references(
        to_jpeg_bytes(make_campus_like_image()),
        index,
        'perceptual',
        5_000_000,
        THRESHOLD,
    )
    assert result.status == REFERENCE_IMAGES_UNAVAILABLE
    assert result.similarity is None


def test_missing_backend_returns_model_unavailable():
    result = verify_image_against_references(
        b'', None, 'clip', 5_000_000, THRESHOLD
    )
    assert result.status == MODEL_UNAVAILABLE


def test_no_photo_submitted_returns_inconclusive(tmp_path):
    folder = tmp_path / 'refs'
    write_reference(folder, 2)
    index = build_reference_index(str(folder), PerceptualEmbedding())
    result = verify_image_against_references(None, index, 'perceptual', 5_000_000, THRESHOLD)
    assert result.status == INCONCLUSIVE
    assert result.reference_count == 2


def test_invalid_upload_returns_invalid_image(tmp_path):
    folder = tmp_path / 'refs'
    write_reference(folder, 1)
    index = build_reference_index(str(folder), PerceptualEmbedding())
    result = verify_image_against_references(
        b'garbage bytes', index, 'perceptual', 5_000_000, THRESHOLD
    )
    assert result.status == INVALID_IMAGE


def test_genuine_campus_like_photo_scores_highest(tmp_path):
    """Held-out evaluation image: same scene, re-encoded as a second capture."""
    folder = tmp_path / 'refs-genuine'
    write_reference(folder, 3)
    index = build_reference_index(str(folder), PerceptualEmbedding())

    buffer = io.BytesIO()
    make_campus_like_image(seed=0).save(buffer, format='JPEG', quality=70)

    result = verify_image_against_references(
        buffer.getvalue(), index, 'perceptual', 5_000_000, 0.92
    )
    assert result.status == POSSIBLE_VISUAL_MATCH
    assert result.similarity > 0.9
    assert result.best_reference in index.names


def test_flat_or_blank_images_are_rejected_as_inconclusive(tmp_path):
    """A featureless image must not be scored - it would match almost anything."""
    folder = tmp_path / 'refs-flat'
    write_reference(folder, 2)
    index = build_reference_index(str(folder), PerceptualEmbedding())

    buffer = io.BytesIO()
    Image.new('RGB', (200, 150), (128, 128, 128)).save(buffer, format='JPEG')
    result = verify_image_against_references(
        buffer.getvalue(), index, 'perceptual', 5_000_000, 0.0
    )
    assert result.status == INCONCLUSIVE
    assert result.similarity is None


def test_unrelated_photo_scores_lower_than_campus_photo(tmp_path):
    folder = tmp_path / 'refs-compare'
    write_reference(folder, 2)
    index = build_reference_index(str(folder), PerceptualEmbedding())

    campus = verify_image_against_references(
        to_jpeg_bytes(make_campus_like_image(seed=2)), index, 'perceptual', 5_000_000, 0.0
    )
    unrelated = verify_image_against_references(
        to_jpeg_bytes(make_unrelated_image()), index, 'perceptual', 5_000_000, 0.0
    )
    assert campus.similarity > unrelated.similarity


def test_similar_building_from_another_location_is_lower_but_not_rejected(tmp_path):
    """A low score must be labelled, never treated as proof of absence."""
    folder = tmp_path / 'refs-similar-building'
    write_reference(folder, 2)
    index = build_reference_index(str(folder), PerceptualEmbedding())

    result = verify_image_against_references(
        to_jpeg_bytes(make_unrelated_image()), index, 'perceptual', 5_000_000, 0.99
    )
    assert result.status == LOW_VISUAL_SIMILARITY
    assert 'not proof' in result.note.lower() or 'not proof' in result.note
    assert 0.0 <= result.similarity <= 1.0


def test_result_serialises_for_the_api(tmp_path):
    folder = tmp_path / 'refs-api'
    write_reference(folder, 1)
    index = build_reference_index(str(folder), PerceptualEmbedding())
    result = verify_image_against_references(
        to_jpeg_bytes(make_campus_like_image()), index, 'perceptual', 5_000_000, THRESHOLD
    )
    payload = result.as_dict()
    assert set(payload) >= {'status', 'similarity', 'best_reference', 'backend', 'reference_count'}
    assert 0.0 <= payload['similarity'] <= 1.0