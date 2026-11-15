// Rekordy dla trybów jednoosobowych (localStorage przeglądarki)
export function saveRecord(mode, value, lowerIsBetter, fmt) {
  try {
    const key = `arcade_best_${mode}`;
    const old = parseFloat(localStorage.getItem(key));
    const better = Number.isNaN(old) || (lowerIsBetter ? value < old : value > old);
    if (better) {
      localStorage.setItem(key, String(value));
      return 'NEW RECORD';
    }
    return `BEST ${fmt(old)}`;
  } catch {
    return null;
  }
}
