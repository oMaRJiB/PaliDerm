// Progressive enhancements only: authorization and validation stay on the server.
(() => {
  const messages = document.body.dataset;
  // Timestamp display only: SQL and datetime attributes retain their UTC values.
  // SQLite's timezone-less timestamp format explicitly means UTC here. Date-only
  // birthdays/follow-up dates are never selected, avoiding calendar-day shifts.
  const timestamps = document.querySelectorAll('time[data-local-time]');
  if (timestamps.length && typeof Intl !== 'undefined') {
    try {
      const formatter = new Intl.DateTimeFormat(document.documentElement?.lang || undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
      });
      let converted = false;
      timestamps.forEach(element => {
        let raw = element.getAttribute('datetime').trim().replace(' ', 'T');
        if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/.test(raw)) return;
        if (!/(?:Z|[+-]\d{2}:?\d{2})$/.test(raw)) raw += 'Z';
        const instant = new Date(raw);
        if (Number.isNaN(instant.getTime())) return;
        element.title = element.textContent; // Original UTC value remains inspectable.
        element.textContent = formatter.format(instant);
        converted = true;
      });
      const notice = document.querySelector('[data-timezone-notice]');
      if (converted && notice) {
        notice.textContent = messages.timeLocal;
        notice.hidden = false;
      }
    } catch (_) {
      // Unsupported Intl/device settings leave explicitly labeled UTC intact.
    }
  }
  function feedback(form) {
    let box = form.querySelector('.form-feedback');
    if (!box) {
      box = document.createElement('p');
      box.className = 'form-feedback';
      box.setAttribute('role', 'status');
      box.tabIndex = -1;
      form.append(box);
    }
    return box;
  }
  function restore(form) {
    delete form.dataset.submitting;
    form.removeAttribute('aria-busy');
    form.querySelectorAll('[data-disabled-by-submit]').forEach(button => {
      button.disabled = false;
      delete button.dataset.disabledBySubmit;
    });
  }
  document.addEventListener('submit', async event => {
    const form = event.target;
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post') return;
    if (form.dataset.submitting) { event.preventDefault(); return; }
    const confirmation = form.querySelector('[data-confirm]');
    if (confirmation && !window.confirm(confirmation.dataset.confirm)) {
      event.preventDefault(); return;
    }
    // Without fetch/FormData, preserve ordinary browser form submission.
    if (!window.fetch || !window.FormData) return;
    event.preventDefault();
    const payload = new FormData(form);
    if (event.submitter?.name) payload.append(event.submitter.name, event.submitter.value);
    form.dataset.submitting = '1';
    form.setAttribute('aria-busy', 'true');
    form.querySelectorAll('button:not(:disabled), input[type=submit]:not(:disabled)').forEach(button => {
      button.dataset.disabledBySubmit = '1';
      button.disabled = true;
    });
    const box = feedback(form);
    box.setAttribute('role', 'status');
    box.textContent = messages.working;
    try {
      // Named controls (such as name="action") can shadow form.action.
      // Read HTML attributes so assignment/revision/close keep their actual URL.
      const response = await fetch(form.getAttribute('action') || window.location.href, {method: 'POST', body: payload, credentials: 'same-origin', headers: {'X-Form-Response': 'json'}});
      if (response.ok && response.headers.get('content-type')?.includes('application/json')) {
        const result = await response.json();
        const destination = new URL(result.redirect, window.location.href);
        if (destination.origin !== window.location.origin) throw new Error();
        window.location.assign(destination.href);
        return;
      }
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      box.textContent = html.querySelector('[role=alert]')?.textContent || messages.networkError;
      box.setAttribute('role', 'alert');
      restore(form);
      box.focus();
    } catch (_) {
      // A lost response may follow a committed write: ask users to check before retrying.
      box.textContent = messages.networkError;
      box.setAttribute('role', 'alert');
      restore(form);
      box.focus();
    }
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('form').forEach(restore));
  document.getElementById('return-to-form')?.addEventListener('click', () => history.back());

  document.querySelectorAll('.intake-form').forEach(form => {
    const selector = form.querySelector('[name=photo_body_site]');
    const sync = () => {
      const selected = Array.from(form.querySelectorAll('[name=body_sites]:checked')).map(input => input.value);
      Array.from(selector.options).forEach(option => { option.disabled = !selected.includes(option.value); });
      if (!selected.includes(selector.value)) selector.value = selected[0] || '';
    };
    form.querySelectorAll('[name=body_sites]').forEach(input => input.addEventListener('change', sync));
    sync();
  });
  document.querySelectorAll('input[type=file][data-image-input]').forEach(input => {
    const previews = document.createElement('div');
    previews.className = 'previews';
    previews.setAttribute('aria-live', 'polite');
    previews.setAttribute('aria-label', messages.selectedPreview);
    input.closest('label').after(previews);
    let urls = [];
    const release = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; };
    const render = () => {
      release(); previews.replaceChildren();
      Array.from(input.files).forEach((file, index) => {
        const figure = document.createElement('figure');
        const caption = document.createElement('figcaption');
        caption.dir = 'auto'; caption.textContent = file.name;
        const img = document.createElement('img');
        img.alt = messages.selectedPreview;
        const url = URL.createObjectURL(file); urls.push(url); img.src = url;
        img.addEventListener('error', () => {
          img.remove();
          const warning = document.createElement('p');
          warning.textContent = messages.previewUnavailable;
          figure.prepend(warning);
        });
        figure.append(img, caption);
        // FileList replacement is optional; native input still works if unsupported.
        if (typeof DataTransfer !== 'undefined') {
          const remove = document.createElement('button');
          remove.type = 'button'; remove.className = 'secondary';
          remove.textContent = messages.remove;
          remove.setAttribute('aria-label', `${messages.remove}: ${file.name}`);
          remove.addEventListener('click', () => {
            const transfer = new DataTransfer();
            Array.from(input.files).forEach((item, i) => { if (i !== index) transfer.items.add(item); });
            input.files = transfer.files;
            render(); input.focus();
          });
          figure.append(remove);
        }
        previews.append(figure);
      });
    };
    input.addEventListener('change', render);
    window.addEventListener('pagehide', release);
    window.addEventListener('pageshow', render);
  });
})();
