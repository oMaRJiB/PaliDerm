// Live capture is optional. Native phone capture and ordinary file selection remain available.
(() => {
  document.querySelectorAll('[data-camera]').forEach(camera => {
    const input = camera.closest('form').querySelector('input[name=camera]');
    const start = camera.querySelector('[data-camera-start]');
    const panel = camera.querySelector('[data-camera-panel]');
    const capture = camera.querySelector('[data-camera-capture]');
    const video = camera.querySelector('video');
    const message = camera.querySelector('[data-camera-message]');
    if (!navigator.mediaDevices?.getUserMedia || typeof DataTransfer === 'undefined') return;
    start.hidden = false;
    let stream = null;
    let generation = 0;
    const stop = () => {
      generation++;
      stream?.getTracks().forEach(track => track.stop());
      stream = null; video.srcObject = null;
      panel.hidden = true; capture.disabled = true; start.disabled = false;
      message.textContent = '';
    };
    start.addEventListener('click', async () => {
      const attempt = ++generation;
      start.disabled = true;
      try {
        const opened = await navigator.mediaDevices.getUserMedia({video: {facingMode: {ideal: 'environment'}, width: {ideal: 1920}, height: {ideal: 1440}}, audio: false});
        if (attempt !== generation) { opened.getTracks().forEach(track => track.stop()); return; }
        stream = opened; video.srcObject = opened;
        panel.hidden = false;
        await video.play();
        if (attempt !== generation) return;
        message.textContent = camera.dataset.ready;
      } catch (_) {
        if (attempt !== generation) return;
        stop(); message.textContent = camera.dataset.error;
      }
    });
    video.addEventListener('loadeddata', () => { capture.disabled = !video.videoWidth; });
    capture.addEventListener('click', async () => {
      if (!video.videoWidth || !video.videoHeight || !stream) return;
      capture.disabled = true;
      const attempt = generation;
      try {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        const context = canvas.getContext('2d');
        if (!context) throw new Error();
        context.drawImage(video, 0, 0);
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.95));
        if (attempt !== generation) return;
        if (!blob) throw new Error();
        const files = new DataTransfer();
        files.items.add(new File([blob], camera.dataset.filename, {type: 'image/jpeg'}));
        input.files = files.files;
        input.dispatchEvent(new Event('change', {bubbles: true}));
        stop(); message.textContent = camera.dataset.taken;
        input.focus();
      } catch (_) {
        if (attempt !== generation) return;
        capture.disabled = false;
        message.textContent = camera.dataset.captureError;
      }
    });
    camera.querySelector('[data-camera-stop]').addEventListener('click', stop);
    // Stop device tracks before navigating or sending a form.
    camera.closest('form').addEventListener('submit', stop);
    window.addEventListener('pagehide', stop);
  });
})();
