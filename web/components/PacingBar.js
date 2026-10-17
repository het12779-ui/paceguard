import { percent } from '../format.js';

export default {
  name: 'PacingBar',
  props: {
    item: { type: Object, required: true },
  },
  computed: {
    spentPct() {
      const budget = Math.max(this.item.total_budget_cents, 1);
      return Math.min(100, (this.item.spent_to_date_cents / budget) * 100);
    },
    targetPct() {
      const budget = Math.max(this.item.total_budget_cents, 1);
      return Math.min(100, (this.item.target_to_date_cents / budget) * 100);
    },
    caption() {
      if (this.item.mode === 'asap') return 'spend as fast as possible';
      return `${percent(this.item.progress_ratio)} of plan`;
    },
  },
  template: `
    <div class="pacing">
      <div
        class="pacing-track"
        role="img"
        :aria-label="'Spent ' + percent(item.spent_to_date_cents / Math.max(item.total_budget_cents, 1)) +
          ' of budget, target ' + percent(targetPct / 100)"
      >
        <div class="pacing-fill" :class="'fill-' + item.state" :style="{ width: spentPct + '%' }"></div>
        <div class="pacing-target" :style="{ left: targetPct + '%' }"></div>
      </div>
      <div class="pacing-caption">
        <span>{{ caption }}</span>
        <span>day {{ item.flight_day }}/{{ item.flight_days }}</span>
      </div>
    </div>
  `,
  methods: { percent },
};
