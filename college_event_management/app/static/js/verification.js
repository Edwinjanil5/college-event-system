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
    resultPanel: document.getElementById('resultPanel'),
    verdictBadge: document.getElementById('verdictBadge'),
    probabilityBar: document.getElementById('probabilityBar'),
    resultDistance: document.getElementById('resultDistance'),
    resultProbability: document.getElementById('resultProbability'),
    resultCampus: document.getElementById('resultCampus'),
    resultModel: document.getElementById('resultModel'),
    resultSimulated: document.getElementById('resultSimulated')
  };

  if (!eventId || !els.check) {
    return;
  }

  var stream = null;
  var photoDataUrl = null;
  var candidate = null;

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
    candidate = { point: point, source: source };
    els.locationDetails.hidden = false;
    els.candidateLat.textContent = Number(point.latitude).toFixed(6);
    els.candidateLng.textContent = Number(point.longitude).toFixed(6);
    els.candidateAccuracy.textContent = point.accuracy_m ? point.accuracy_m.toFixed(1) + ' m' : 'not reported';
    els.candidateSource.textContent = source === 'random_shot' ? 'Random shot (demo)' : 'Device GPS';
    els.check.disabled = false;
    els.locationStatus.textContent = source === 'random_shot'
      ? 'Random geolocation generated. Run the comparison to see the model verdict.'
      : 'Current location captured. Run the comparison to cross-match it with the campus.';
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
    if (!candidate) { return; }
    els.check.disabled = true;
    els.resultStatus.textContent = 'Comparing the two geolocations...';

    var payload = {
      latitude: candidate.point.latitude,
      longitude: candidate.point.longitude,
      accuracy: candidate.point.accuracy_m,
      source: candidate.source,
      image: photoDataUrl
    };

    fetch('/verify/' + eventId + '/check', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload)
    })
      .then(function (response) { return response.json().then(function (data) { return { ok: response.ok, data: data }; }); })
      .then(function (result) {
        els.check.disabled = false;
        if (!result.ok) {
          els.resultStatus.textContent = result.data.error || 'The comparison could not be completed.';
          return;
        }
        renderResult(result.data);
      })
      .catch(function () {
        els.check.disabled = false;
        els.resultStatus.textContent = 'The comparison could not be completed.';
      });
  }

  function renderResult(data) {
    els.resultStatus.textContent = 'Comparison complete.';
    els.resultPanel.hidden = false;
    els.verdictBadge.textContent = data.verdict === 'match' ? 'Location matched' : 'Location mismatch';
    els.verdictBadge.className = 'badge fs-6 ' + (data.verdict === 'match' ? 'bg-success' : 'bg-danger');

    var percent = Math.round((data.probability || 0) * 100);
    els.probabilityBar.style.width = percent + '%';
    els.probabilityBar.textContent = percent + '%';
    els.probabilityBar.className = 'progress-bar ' + (data.verdict === 'match' ? 'bg-success' : 'bg-danger');

    els.resultDistance.textContent = Number(data.distance_m).toLocaleString() + ' m';
    els.resultProbability.textContent = percent + '%';
    els.resultCampus.textContent = data.campus.name + ' (' + data.campus.latitude.toFixed(5) + ', ' + data.campus.longitude.toFixed(5) + ')';
    els.resultModel.textContent = data.model.version + ' - accuracy ' + data.model.accuracy + '%';
    els.resultSimulated.textContent = data.source === 'random_shot' ? 'Yes (random shot)' : 'No (device GPS)';
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
