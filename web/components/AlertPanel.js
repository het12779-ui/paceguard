const KIND_LABELS = {
  PROJECTED_OVERSPEND: 'Projected overspend',
  UNDER_PACE: 'Under-pacing',
  BUDGET_EXHAUSTED: 'Budget exhausted',
  DAILY_CAP_BREACH: 'Daily cap breach',
  DELIVERY_STALLED: 'Delivery stalled',
};

export default {
  name: 'AlertPanel',
  props: {
    alerts: { type: Array, default: () => [] },
    resolvingId: { type: Number, default: null },
  },
  emits: ['resolve'],
  methods: {
    kindLabel(kind) {
      return KIND_LABELS[kind] || kind.replaceAll('_', ' ').toLowerCase();
    },
    timeAgo(iso) {
      // API timestamps are naive UTC; mark them as such before parsing.
      const then = new Date(`${iso}Z`).getTime();
      const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
      if (minutes < 1) return 'just now';
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.round(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      return `${Math.round(hours / 24)}d ago`;
    },
  },
  template: `
    <section class="panel" aria-labelledby="alerts-title">
      <div class="panel-head">
        <div class="panel-title" id="alerts-title">Guardrails</div>
        <div class="panel-meta">{{ alerts.length }} open</div>
      </div>

      <div v-if="alerts.length" class="alerts">
        <article v-for="alert in alerts" :key="alert.id" class="alert" :class="alert.severity">
          <div class="alert-bar" aria-hidden="true"></div>
          <div class="alert-body">
            <div class="alert-message">{{ alert.message }}</div>
            <div class="alert-meta">
              <span>{{ kindLabel(alert.kind) }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ timeAgo(alert.created_at) }}</span>
              <button
                class="resolve"
                type="button"
                :disabled="resolvingId === alert.id"
                @click="$emit('resolve', alert.id)"
              >
                {{ resolvingId === alert.id ? 'Resolving…' : 'Resolve' }}
              </button>
            </div>
          </div>
        </article>
      </div>

      <div v-else class="empty">
        <strong>All clear</strong>
        No open guardrail alerts for this account.
      </div>
    </section>
  `,
};
