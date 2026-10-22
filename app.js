document.querySelectorAll('input[type="date"]').forEach((input) => {
  if (!input.value) input.max = new Date().toISOString().slice(0, 10);
});
document.querySelectorAll('.flash').forEach((el) => {
  window.setTimeout(() => {
    el.style.opacity = '0';
    window.setTimeout(() => el.remove(), 350);
  }, 5000);
});
