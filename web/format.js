// Money is integer minor units (paise) everywhere in the API. Only this file
// turns it into something a human reads.

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 0,
});

const inrExact = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function money(cents) {
  return inr.format((cents || 0) / 100);
}

export function moneyExact(cents) {
  return inrExact.format((cents || 0) / 100);
}

export function compact(cents) {
  const rupees = (cents || 0) / 100;
  if (Math.abs(rupees) >= 1e7) return `₹${(rupees / 1e7).toFixed(2)}Cr`;
  if (Math.abs(rupees) >= 1e5) return `₹${(rupees / 1e5).toFixed(2)}L`;
  if (Math.abs(rupees) >= 1e3) return `₹${(rupees / 1e3).toFixed(1)}K`;
  return `₹${rupees.toFixed(0)}`;
}

export function percent(value, digits = 0) {
  return `${((value || 0) * 100).toFixed(digits)}%`;
}

export function shortDate(iso) {
  const date = new Date(`${iso}T00:00:00`);
  return date.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' });
}

export function todayISO() {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

export const STATE_LABELS = {
  on_track: 'On track',
  underspending: 'Under',
  overspending: 'Over',
  exhausted: 'Exhausted',
  not_started: 'Scheduled',
  completed: 'Completed',
};
