/* Camera + geolocation capture for CampusPulse location verification.
 *
 * Nothing is captured automatically: the camera stream and the GPS reading are
 * only requested when the student presses the corresponding button, and the
 * photo is discarded unless the comparison is submitted.
 */
(function () {
  'use strict';

  var appRoot = document.getElementById('verifyApp');
  var eventId = appRoot ? appRoot.getAttribute('data-verify-event') : null;
  var csrfMeta = document.querySelector('meta[name="csrf-token"]');
  var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

  var els = {
    preview: document.getElementById('cameraPreview'),
    still: document.getElementById('cameraStill'),
    placeholder: document.getElementById('cameraPlaceholder'),
    startCamera: document.getElementById('startCameraBtn'),
    capture: document.getElementById('captureBtn'),
    retake: document.getElementById('retakeBtn'),
    stopCamera: document.getElementById('stopCameraBtn'),
    cameraStatus: document.getElementById('cameraStatus'),
    locate: document.getElementById('locateBtn'),
    randomShot: document.getElementById('randomShotBtn'),
    locationStatus: document.getElementById('locationStatus'),
    locationDetails: document.getElementById('locationDetails'),
    candidateLat: document.getElementById('candidateLat'),
    candidateLng: document.getElementById('candidateLng'),
    candidateAccuracy: document.getElementById('candidateAccuracy'),
    candidateSource: document.getElementById('candidateSource'),
    check: document.getElementById('checkBtn'),
    resultStatus: document.getElementById('resultStatus'),
    resultLoading: document.getElementById('resultLoading'),
    resultPanel: document.getElementById('resultPanel'),
    gpsBadge: document.getElementById('gpsBadge'),
    gpsDistance: document.getElementById('gpsDistance'),
    gpsAccuracy: document.getElementById('gpsAccuracy'),
    gpsReason: document.getElementById('gpsReason'),
    imageBadge: document.getElementById('imageBadge'),
    imageReference: document.getElementById('imageReference'),
    imageSimilarity: document.getElementById('imageSimilarity'),
    imageCount: document.getElementById('imageCount'),
    imageReason: document.getElementById('imageReason'),
    decisionBadge: document.getElementById('decisionBadge'),
    decisionRationale: document.getElementById('decisionRationale'),
    decisionMessage: document.getElementById('decisionMessage')
  };

  if (!eventId || !els.check) {
    return;
  }

  var stream = null;
  var photoDataUrl = null;
  var candidate = null;
  var submitted = false;

  function setCameraStatus(message) {
    els.cameraStatus.textContent = message;
  }

  function stopStream() {
    if (stream) {
      stream.getTracks().forEach(function (track) { track.stop(); });
      stream = null;
    }
    if (els.preview) {
      els.preview.srcObject = null;
      els.preview.hidden = true;
    }
  }

  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraStatus('This browser does not support camera capture. You can still run the location comparison.');
      return;
    }
    setCameraStatus('Requesting camera permission...');
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
      .then(function (mediaStream) {
        stream = mediaStream;
        els.preview.srcObject = mediaStream;
        els.preview.hidden = false;
        els.placeholder.hidden = true;
        els.still.hidden = true;
        els.capture.disabled = false;
        els.stopCamera.disabled = false;
        setCameraStatus('Camera is on. Nothing is stored until you capture and submit.');
      })
      .catch(function (error) {
        stream = null;
        setCameraStatus(cameraErrorMessage(error));
      });
  }

  function cameraErrorMessage(error) {
    if (!error) { return 'Camera could not be started.'; }
    if (error.name === 'NotAllowedError') {
      return 'Camera permission was denied. Allow camera access in your browser settings to attach a photo.';
    }
    if (error.name === 'NotFoundError') {
      return 'No camera was found on this device.';
    }
    if (error.name === 'NotReadableError') {
      return 'The camera is already in use by another application.';
    }
    return 'Camera could not be started (' + error.name + ').';
  }

  function capturePhoto() {
    if (!stream || !els.preview) { return; }
    var video = els.preview;
    var width = video.videoWidth || 640;
    var height = video.videoHeight || 480;
    var canvas = document.createElement('canvas');
    var scale = Math.min(1, 640 / width);
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    var context = canvas.getContext('2d');
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    try {
      photoDataUrl = canvas.toDataURL('image/jpeg', 0.6);
    } catch (error) {
      setCameraStatus('The photo could not be processed.');
      return;
    }
    stopStream();
    els.still.src = photoDataUrl;
    els.still.hidden = false;
    els.capture.disabled = true;
    els.stopCamera.disabled = true;
    els.retake.hidden = false;
    setCameraStatus('Photo captured. It will be sent only if you run the comparison.');
  }

  function resetPhoto() {
    photoDataUrl = null;
    els.still.hidden = true;
    els.still.removeAttribute('src');
    els.retake.hidden = true;
    els.placeholder.hidden = false;
  }

  function showCandidate(point, source) {
    candidate = { point: point, source: source, capturedAt: new Date().toISOString() };
    els.locationDetails.hidden = false;
    els.candidateLat.textContent = Number(point.latitude).toFixed(6);
    els.candidateLng.textContent = Number(point.longitude).toFixed(6);
    els.candidateAccuracy.textContent = point.accuracy_m ? point.accuracy_m.toFixed(1) + ' m' : 'not reported';
    els.candidateSource.textContent = source === 'random_shot' ? 'Random shot (demo)' : 'Device GPS';
    els.check.disabled = false;
    els.locationStatus.textContent = source === 'random_shot'
      ? 'Random geolocation generated. Run the verification to see the model verdict.'
      : 'Current location captured. Run the verification to cross-match it with the campus.';
  }

  function useCurrentLocation() {
    if (!navigator.geolocation) {
      els.locationStatus.textContent = 'This browser does not support geolocation.';
      return;
    }
    els.locationStatus.textContent = 'Requesting location permission...';
    navigator.geolocation.getCurrentPosition(
      function (position) {
        showCandidate({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_m: position.coords.accuracy
        }, 'device');
      },
      function (error) {
        var message = 'Location could not be read.';
        if (error && error.code === 1) {
          message = 'Location permission was denied. You can still use the random shot demo.';
        } else if (error && error.code === 2) {
          message = 'Your location is currently unavailable. Try again outdoors.';
        } else if (error && error.code === 3) {
          message = 'Reading your location timed out. Try again.';
        }
        els.locationStatus.textContent = message;
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  }

  function generateRandomShot() {
    els.locationStatus.textContent = 'Generating a random geolocation...';
    fetch('/verify/' + eventId + '/random-shot', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({})
    })
      .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
      .then(function (payload) {
        if (!payload.ok) {
          els.locationStatus.textContent = payload.data.error || 'Random shot could not be generated.';
          return;
        }
        showCandidate(payload.data.point, 'random_shot');
        els.locationStatus.textContent = payload.data.simulated_inside_campus
          ? 'Random geolocation generated (simulated inside the campus area).'
          : 'Random geolocation generated (simulated away from the campus).';
      })
      .catch(function () {
        els.locationStatus.textContent = 'Random shot could not be generated.';
      });
  }

  function runComparison() {
    if (!candidate || submitted) { return; }
    submitted = true;
    els.check.disabled = true;
    els.resultLoading.classList.remove('d-none');
    els.resultStatus.textContent = 'Submitting your location and photo for verification...';

    var payload = {
      latitude: candidate.point.latitude,
      longitude: candidate.point.longitude,
      accuracy: candidate.point.accuracy_m,
      source: candidate.source,
      captured_at: candidate.capturedAt,
      image: photoDataUrl
    };

    fetch('/verify/' + eventId + '/check', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, data: data };
        });
      })
      .then(function (result) {
        els.resultLoading.classList.add('d-none');
        if (!result.ok) {
          // The submission never reached the server, so a retry is safe.
          submitted = false;
          els.check.disabled = false;
          els.resultStatus.textContent = result.data.error || 'The verification could not be completed.';
          return;
        }
        renderResult(result.data);
      })
      .catch(function () {
        els.resultLoading.classList.add('d-none');
        // The captured photo is deliberately kept so nothing is lost.
        submitted = false;
        els.check.disabled = false;
        els.resultStatus.textContent =
          'The network request failed. Your photo is still here - press Run verification to try again.';
      });
  }

  var GPS_STYLES = {
    LOCATION_MATCH: ['Location matched', 'bg-success'],
    LOCATION_MISMATCH: ['Away from campus', 'bg-danger'],
    INCONCLUSIVE: ['Inconclusive', 'bg-warning text-dark'],
    MISSING: ['No location provided', 'bg-secondary']
  };

  var IMAGE_STYLES = {
    POSSIBLE_VISUAL_MATCH: ['Possible visual match', 'bg-success'],
    LOW_VISUAL_SIMILARITY: ['Low visual similarity', 'bg-warning text-dark'],
    INCONCLUSIVE: ['Inconclusive', 'bg-secondary'],
    REFERENCE_IMAGES_UNAVAILABLE: ['No reference images', 'bg-secondary'],
    MODEL_UNAVAILABLE: ['Comparison unavailable', 'bg-secondary'],
    INVALID_IMAGE: ['Image not readable', 'bg-danger']
  };

  function applyBadge(element, styles, key, fallbackLabel) {
    var entry = styles[key];
    element.textContent = entry ? entry[0] : (key ? key.replace(/_/g, ' ').toLowerCase() : fallbackLabel);
    element.className = 'badge fs-6 ' + (entry ? entry[1] : 'bg-secondary');
  }

  function renderResult(data) {
    var gps = data.gps_verification || {};
    var image = data.image_verification || {};

    els.resultStatus.textContent = 'Verification complete.';
    els.resultPanel.hidden = false;

    applyBadge(els.gpsBadge, GPS_STYLES, gps.status, 'unknown');
    els.gpsDistance.textContent = gps.distance_meters != null
      ? Number(gps.distance_meters).toLocaleString() + ' m' : 'not available';
    els.gpsAccuracy.textContent = gps.accuracy_meters != null
      ? Number(gps.accuracy_meters).toLocaleString() + ' m' : 'not reported';
    els.gpsReason.textContent = gps.reason || 'The reading was precise enough to compare.';

    applyBadge(els.imageBadge, IMAGE_STYLES, image.status, 'unknown');
    els.imageReference.textContent = image.best_reference || 'none';
    els.imageSimilarity.textContent = image.similarity != null
      ? Number(image.similarity).toFixed(3) : 'not available';
    els.imageCount.textContent = image.reference_count != null ? image.reference_count : 0;
    els.imageReason.textContent = image.reason || 'The photo was compared with the campus references.';

    var suggested = data.final_decision === 'SUGGESTED_CAMPUS_MATCH';
    els.decisionBadge.textContent = suggested ? 'Suggested campus match' : 'Faculty review';
    els.decisionBadge.className = 'badge fs-6 ' + (suggested ? 'bg-info text-dark' : 'bg-primary');
    els.decisionRationale.textContent = data.rationale || '';
    els.decisionMessage.textContent = data.message ||
      'Your submission was recorded and sent for faculty review.';

    // Prevent an accidental duplicate submission of the same evidence.
    els.check.disabled = true;
  }

  els.startCamera.addEventListener('click', startCamera);
  els.capture.addEventListener('click', capturePhoto);
  els.retake.addEventListener('click', function () {
    resetPhoto();
    startCamera();
  });
  els.stopCamera.addEventListener('click', function () {
    stopStream();
    els.capture.disabled = true;
    els.stopCamera.disabled = true;
    setCameraStatus('Camera stopped.');
  });
  els.locate.addEventListener('click', useCurrentLocation);
  els.randomShot.addEventListener('click', generateRandomShot);
  els.check.addEventListener('click', runComparison);

  window.addEventListener('beforeunload', stopStream);
})();
