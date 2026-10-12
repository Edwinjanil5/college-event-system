# Campus reference images

Four campus photographs are installed here:

```
campus.jpg
corridor.avif
main_entrance.jpg
rear_view.jpeg
```

Replace, add or remove them freely — nothing here needs retraining or a code
change. Embeddings are cached by file content hash, so only changed files are
re-embedded.

Suggested additional images if you capture more:

## Accepted files

| | |
|---|---|
| Formats | `.jpg`, `.jpeg`, `.png`, `.webp`, `.avif` |
| Maximum size | 10 MB per image (`MAX_REFERENCE_IMAGE_BYTES`) |
| Recommended | Exterior views of the main academic block, gate, or campus buildings, shot in daylight |

Adding up to five:

```
main-block.jpg
academic-block.jpg
gate.jpg
library.jpg
hostel.jpg
```

## What this folder does and does not do

* With **no images** the system still works: the location check runs on its own
  and the photo result is reported as `REFERENCE_IMAGES_UNAVAILABLE`.
* With **one to five images** the system embeds each photograph once and compares
  an uploaded photo against them using cosine similarity.
* Adding, removing or replacing a file here needs **no retraining and no code
  change**. Embeddings are cached and keyed by file content hash, so only the
  changed images are re-embedded.

## Honest limitations

Five photographs are **not** enough to train a reliable college-specific image
classifier, and nothing in this module attempts that. The comparison is a
low-level visual fingerprint (layout, colour and edge signature) computed with
Pillow. It produces an *indicative* label only:

* `POSSIBLE_VISUAL_MATCH` - the photo resembles a reference image
* `LOW_VISUAL_SIMILARITY` - it does not resemble the reference set
* `INCONCLUSIVE` - no usable photo was submitted
* `REFERENCE_IMAGES_UNAVAILABLE` - the folder is empty
* `MODEL_UNAVAILABLE` - the configured embedding backend could not be loaded
* `INVALID_IMAGE` - the uploaded file could not be read as an image

A low similarity score is **not** evidence that a student was absent. Weather,
lighting, cropping, camera quality and different angles all reduce similarity.
Cosine similarity is not a probability and must never be presented as one.

## Using a stronger model

The backend is configurable. Set `IMAGE_EMBEDDING_BACKEND=clip` to use a
pretrained CLIP model instead, which needs PyTorch and `open_clip_torch`
installed separately. See `docs/VERIFICATION_MODULE.md` for the exact
commands, the reasons it is not the default, and the deployment constraints.