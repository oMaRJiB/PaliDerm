// Native forms work without JavaScript. Prevent accidental double clicks after validation.
document.addEventListener('submit', event => {
  if (event.target.method.toLowerCase() !== 'post') return;
  if (event.target.dataset.submitting) { event.preventDefault(); return; }
  event.target.dataset.submitting = '1';
  event.target.querySelectorAll('button').forEach(button => { button.disabled = true; });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('form').forEach(form => {
    delete form.dataset.submitting;
    form.querySelectorAll('button').forEach(button => { button.disabled = false; });
  });
});

document.getElementById('return-to-form')?.addEventListener('click', () => history.back());
