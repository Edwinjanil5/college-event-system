# AI-Assisted Geolocation and Image Verification

CampusPulse verification module for the **College of Applied Sciences, Adoor
(IHRD)**. It checks whether a student's submitted location and photo are
*consistent with* the campus, and routes the result to a human reviewer.

> **Read this first.** Neither signal proves physical presence. A browser
> location is untrusted input, and a visual match is not proof that a
> photograph was taken at the college. Every outcome is advisory and a person
> makes the decision.

---

## 1. Architecture discovered

CampusPulse is a **Flask** application. It is not FastAPI, and this module was
built to fit what already exists rather than introduce a second service.

| Layer | Technology |
|---|---|
| Backend | Flask 3.0 (Blueprints, Flask-Login sessions) |
| Frontend | Server-rendered Jinja2 + vanilla JS (no build step) |
| Database | SQLAlchemy 2.x, SQLite by default, MySQL supported |
| Auth | Flask-Login session cookie, roles `student`, `organizer`, `hod`, `admin` |
| CSRF | Flask-WTF `CSRFProtect` on all state-changing requests |
| Migrations | Alembic (`flask db upgrade`) |
| Tests | pytest |
| Deploy | Vercel (Flask WSGI) + packaged Windows desktop build (PyInstaller) |

### Why there is no FastAPI service

The specification allows FastAPI *if appropriate to the existing architecture*.
Adding it would mean a second process, a second port, CORS, a second deployment
target, and a split auth model — for one JSON endpoint the existing blueprint
already serves. The verification API is therefore a Flask blueprint
(`/verify/...`) on the same origin as the frontend.

**Consequence for CORS:** none is needed or configured. The frontend and API are
same-origin, so no cross-origin request is ever made and no wildcard header is
exposed. If you *do* split the service later, enable CORS for the single
CampusPulse origin only — never `*`.

---

## 2. Files created

| File | Purpose |
|---|---|
| `app/campus.py` | Campus model (reference point, radius, optional GeoJSON polygon), haversine maths, point-in-polygon, coordinate validation, GPS outcome classification, coordinate masking |
| `app/image_verification.py` | Safe image decoding, pluggable embedding backends, cached reference index, cosine similarity, indicative labels |
| `app/decision.py` | Pure decision logic combining both signals. No Flask, no database — unit tested on its own |
| `app/controllers/verification.py` | HTTP surface: student submission, status, image serving, faculty review queue and decisions |
| `app/views/verify_location.html` | Student capture + result page (extended, not duplicated) |
| `app/views/verification_review_queue.html` | Faculty review queue |
| `app/views/event_verifications.html` | Organizer per-event summary (extended) |
| `app/static/js/verification.js` | Camera, geolocation, submission, result rendering |
| `migrations/versions/f7a8b9c0d1e2_verification_evidence_and_review.py` | New columns: GPS status, image evidence, decision, review |
| `reference_images/README.md` | Where to put the college photographs |
| `tests/test_campus.py` | GPS tests |
| `tests/test_image_verification.py` | Image tests |
| `tests/test_decision.py` | Decision tests |
| `tests/test_verification.py` | Integration, authorisation, privacy, review tests |
| `docs/VERIFICATION_MODULE.md` | This document |

## 3. Files modified

| File | Change |
|---|---|
| `config/settings.py` | Campus coordinates, radius, polygon path, accuracy limit, similarity threshold, reference folder, backend choice, retention period |
| `app/models/__init__.py` | `GeoVerification` gains GPS status/reason, image evidence, combined decision and human-review columns; coordinates made nullable |
| `app/controllers/organizer.py` | Event verification summary uses the new columns |
| `app/views/organizer_dashboard.html` | Link to the review queue |
| `app/__init__.py` | `purge-verification-records` and `verification-status` CLI commands |
| `tests/conftest.py` | Verification config, temporary folders, faster bcrypt for tests |
| `.env.example`, `schema.sql`, `README.md` | Documentation of the new configuration and tables |

---

## 4. GPS verification

Reference point (constant, supplied by the college):

```
CAMPUS_LATITUDE  = 9.1557
CAMPUS_LONGITUDE = 76.7369
CAMPUS_RADIUS_M  = 250
```

The service reports **four** outcomes, not two:

| Status | Meaning |
|---|---|
| `LOCATION_MATCH` | Inside the campus area, with a reading precise enough to tell |
| `LOCATION_MISMATCH` | Outside the campus area, with a reading precise enough to tell |
| `INCONCLUSIVE` | Accuracy is too coarse, or the error circle covers the campus boundary |
| `MISSING` | Coordinates absent or invalid — e.g. permission denied |

`INCONCLUSIVE` is a first-class result. A student standing exactly on the
campus edge with a 5 m-accurate reading gets `INCONCLUSIVE`, because the
reading genuinely cannot separate "inside" from "outside".

Two distances are recorded because they mean different things:

* `distance_m` — distance from the campus **reference point**
* `edge_distance_m` — distance from the campus **boundary**

### Campus polygon

Set `CAMPUS_POLYGON_FILE` to a GeoJSON `Polygon` and it replaces the circular
check automatically. Malformed or too-short polygons are ignored, and the
radius remains the fallback, so a bad file cannot break the feature.

---

## 5. Image comparison

### The approach, and its honest limits

With five or fewer photographs, **training a college-specific classifier is not
possible**. This module therefore performs *visual comparison only*: it embeds
an uploaded image and compares it with embeddings of the reference images using
cosine similarity.

* Five images cannot make a reliable classifier.
* Cosine similarity is **not** a probability and **not** proof of origin.
* `IMAGE_SIMILARITY_THRESHOLD` (default `0.92`) is an **indicative starting
  point**, not a validated decision boundary. Calibrate it on real campus
  photographs before relying on it.

Returned labels:

`POSSIBLE_VISUAL_MATCH` · `LOW_VISUAL_SIMILARITY` · `INCONCLUSIVE` ·
`REFERENCE_IMAGES_UNAVAILABLE` · `MODEL_UNAVAILABLE` · `INVALID_IMAGE`

### Backends and the CLIP compatibility finding

The backend is selectable with `IMAGE_EMBEDDING_BACKEND`.

**`perceptual` (default, shipped).** A deterministic low-level fingerprint —
32×32 grayscale thumbnail, per-pixel horizontal gradients, row/column
brightness profiles and colour means — computed with **Pillow only**. No new
dependency, works offline, no model download.

**`clip` (optional).** A pretrained CLIP model gives semantically meaningful
similarity and is the better choice *if you can afford it*. It was measured, not
assumed:

| Question | Finding |
|---|---|
| Does PyTorch support this Python? | **Yes.** `torch 2.14.1` ships `cp314` wheels, so Python 3.14.6 is supported |
| How large is the Windows wheel? | **124 MB** before dependencies |
| Plus CLIP weights? | ~350 MB downloaded at first use |
| Effect on this project's Vercel deploy? | **Would break it.** The deployment is already 147 MB; Vercel's Lambda limit would be exceeded |
| Effect on the desktop build? | PyInstaller bundle grows past 500 MB |

So CLIP is genuinely available — it is *operationally* prohibitive here, not
impossible. To enable it on a machine that can take the size cost:

```powershell
& .\venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
& .\venv\Scripts\python.exe -m pip install open_clip_torch
$env:IMAGE_EMBEDDING_BACKEND = "clip"
```

No code change is required. If the import fails, the module returns
`MODEL_UNAVAILABLE` instead of crashing.

### Measured behaviour (real campus photographs)

The reference folder holds four real photographs (`campus.jpg`,
`corridor.avif`, `main_entrance.jpg`, `rear_view.jpeg`). Measured on that set:

| Sample | n | Similarity |
|---|---|---|
| Real campus photos + brightness/JPEG variants | 16 | min **0.985**, max 1.000 |
| Synthetic non-campus (gradient) | 1 | **0.424** |
| Synthetic non-campus (random blocks) | 1 | **0.117** |
| Flat grey image | 1 | rejected as `INCONCLUSIVE` |

Separation margin **0.561**. At the default threshold of `0.92`: 16/16 positives
matched, 0/2 negatives matched. Any threshold between **0.50 and 0.95** gives
the same outcome on this data.

Caveat: two negative samples is a very small evaluation set. Re-check the
threshold once more real non-campus photographs exist.

### Two defects found by measuring, and fixed

1. **A flat grey image originally scored 0.92 — the same as a real campus
   photo.** The embedding used raw pixel brightness, so a featureless image
   normalised to a near-identical vector. Fixed by standardising every feature
   block against its own statistics (so the fingerprint describes contrast
   structure, not brightness) and by rejecting near-zero-contrast images before
   scoring.
2. **Whitening against reference-set statistics was implemented, then
   removed.** With only four references those statistics come from too few
   samples and amplified JPEG artefacts — an identical scene scored **1.00 at
   quality 90 but 0.12 at quality 85**. Removing it made the score stable at
   ≥ 0.9999 across every quality level.

### Known weakness

The score is sensitive to **cropping and zoom**: a cropped version of a real
campus photo scored 0.05–0.30, i.e. no match. This fails toward *no match*
rather than toward a false *match*, which is the safer direction — but it means
a student who photographs a building up close will not get a visual match.
CLIP would fix this properly; that is one of the main reasons to enable it.

### Caching

Reference embeddings are cached to `REFERENCE_IMAGE_CACHE_FILE`, keyed by the
SHA-256 of the file contents plus the backend name and version. Adding, removing
or replacing a photograph re-embeds only what changed. A corrupt reference file
is skipped, not fatal.

---

## 6. Combined decision

```json
{
  "gps_verification":  {"status": "LOCATION_MATCH", "distance_meters": 35.2, "accuracy_meters": 12.0},
  "image_verification": {"status": "POSSIBLE_VISUAL_MATCH", "best_reference": "academic-block.jpg", "similarity": 0.87},
  "final_decision": "FACULTY_REVIEW",
  "flags": ["gps_match_but_image_low_similarity"],
  "requires_human_review": true
}
```

Outcomes are `SUGGESTED_CAMPUS_MATCH` or `FACULTY_REVIEW`. **There is no
automatic accept or reject.** `SUGGESTED_CAMPUS_MATCH` requires both signals to
agree, and even then it is recorded as a suggestion awaiting review.

Contradictions are flagged, not resolved silently:

* `gps_match_but_image_low_similarity`
* `image_match_but_gps_mismatch`
* `gps_inconclusive`, `gps_missing`, `image_missing`,
  `image_reference_unavailable`, `image_model_unavailable`, `image_invalid`

Model output and human decisions are stored in **separate columns**
(`final_decision` vs `review_decision`), so a suggestion is never mistaken for a
decision, and a new submission clears any earlier decision.

---

## 7. Security and privacy

| Concern | Measure |
|---|---|
| Identity | Taken from the session only; a student id in the body is ignored |
| Authorisation | Submission needs an approved registration for that event |
| Coordinate validation | Range-checked; NaN/infinity rejected, not coerced |
| File safety | Bytes are decoded and the real format verified; declared MIME type is ignored; 400 KB upload cap; 40 MP Pillow bomb guard |
| Path traversal | Photos are stored under generated UUID filenames and served through an authorised route |
| Precise coordinates | Masked (~100 m) for organizers; exact only for the owner, HoD and admin |
| Photos | Never served from the static folder; owner + authorised reviewers only |
| Logging | Records ids and statuses only, never full coordinates |
| Errors | JSON error strings; no stack traces, paths or secrets reach the client |
| Retention | `VERIFICATION_RETENTION_DAYS` (default 180) with a purge command |
| Camera/mic | `Permissions-Policy: camera=(self), geolocation=(self), microphone=()` |

No facial recognition or identity recognition is used or planned. Location is
requested only for this task, only on an explicit user action, and never in the
background.

**Retention is enforced only if you schedule the purge command.** Run it daily:

```powershell
& .\venv\Scripts\python.exe -m flask --app run.py purge-verification-records
```

---

## 8. PowerShell workflow

```powershell
Set-Location C:\Users\edwin\Downloads\KERALA_AI_TUITION_WEB\college_event_management

# 1. Virtual environment (already provisioned at .\venv)
& .\venv\Scripts\python.exe -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Configuration
Copy-Item .env.example .env        # then edit SECRET_KEY and campus values

# 3. Database
& .\.venv\Scripts\python.exe -m flask --app run.py db upgrade

# 4. Reference photographs (up to five)
Copy-Item C:\path\to\main-block.jpg .\reference_images\

# 5. Confirm the configuration without touching personal data
& .\.venv\Scripts\python.exe -m flask --app run.py verification-status

# 6. Run the app
$env:CAMPUSPULSE_BROWSER = "1"
& .\.venv\Scripts\python.exe run.py

# 7. Tests
& .\.venv\Scripts\python.exe -m pytest -q

# 8. Health / status endpoints
Invoke-RestMethod http://127.0.0.1:5000/health
#   -> {"status":"ok"}
Invoke-RestMethod http://127.0.0.1:5000/verify/status -SessionVariable s   # after login

# 9. Retention (schedule daily)
& .\.venv\Scripts\python.exe -m flask --app run.py purge-verification-records
```

If the app lives inside another project folder, an unrelated `.env` in a parent
directory can leak a `DATABASE_URL` into the Flask CLI. Set
`CAMPUSPULSE_DATABASE_URL` explicitly (the app prefers it).

---

## 9. Tests

143 tests pass (`pytest -q`), up from 52.

| File | Covers |
|---|---|
| `test_campus.py` | Reference point, clearly-inside, clearly-outside, invalid lat/lng, zero/negative/absurd accuracy, poor accuracy, missing permission, boundary ambiguity, configurable threshold, polygon load/fallback, masking |
| `test_image_verification.py` | Genuine campus-like photos, unrelated photos, similar-building photos, unsupported formats, empty files, corrupted images, truncated images, oversized files, 0/1/5 references, missing folder, corrupt reference, cache reuse/invalidation, embedding determinism |
| `test_decision.py` | Every GPS × image combination, contradictions, missing signals, unavailable model, no auto-reject, documented response shape |
| `test_verification.py` | Authenticated/unauthenticated submission, unauthorised events, unknown events, identity from session, duplicate handling, persistence, photo privacy, coordinate masking, review authorisation, retention config |

Evaluation images used for scoring are generated separately from the reference
set, so false positives and false negatives are actually exercised.

**I have not measured real-world accuracy.** The test images are synthetic and
the reference set is empty until you add photographs. Treat the similarity
threshold as unvalidated until calibrated on real campus images.

---

## 10. Known limitations

1. **Only four reference photographs**, and the similarity threshold is
   calibrated on just those (plus two synthetic negatives). Cropped or
   zoomed photos of the same building will not match.
2. **GPS is spoofable.** Desktop and browser tools can forge coordinates. This
   module detects *inconsistency*, not fraud.
3. **Indoor accuracy is poor.** Buildings block signals; indoor readings are
   commonly 30–100 m. The accuracy rules turn that into `INCONCLUSIVE` rather
   than a false accusation.
4. **Similarity threshold is unvalidated** and the perceptual backend is weaker
   than CLIP. CLIP is available but too large to ship by default.
5. **Retention depends on scheduling.** Nothing deletes records unless the purge
   command runs.
6. **The reference point is not a boundary.** A 250 m radius around a single
   coordinate is a starting approximation; add a verified polygon when survey
   data exists.
7. **One submission per student per event** (latest wins). Continuous
   attendance tracking was deliberately not built.
8. **Vercel's database is ephemeral and has no admin bootstrap**, so the live
   demo cannot create an approved event. Use a local run for end-to-end testing.

---

## 11. How a reviewer should read a result

* `LOCATION_MATCH` + `POSSIBLE_VISUAL_MATCH` → the strongest case, still only a
  suggestion. Look at the photo, then confirm.
* `LOCATION_MATCH` + `LOW_VISUAL_SIMILARITY` → probably on campus, wrong photo,
  or a bad angle. Ask, do not accuse.
* `LOCATION_MISMATCH` + `POSSIBLE_VISUAL_MATCH` → the photo may be reused or the
  GPS wrong. Both explanations are plausible.
* `INCONCLUSIVE` / `MISSING` → **no location evidence exists.** Never treat this
  as misconduct; it is usually a weak signal or a denied permission.
* Always read the GPS accuracy before reading the verdict.