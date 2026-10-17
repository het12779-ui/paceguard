import { money, moneyExact, percent, shortDate, STATE_LABELS } from '../format.js';

const WIDTH = 600;
const HEIGHT = 172;
const PAD_TOP = 10;
const PAD_BOTTOM = 26;
const PAD_X = 10;

export default {
  name: 'CampaignDrawer',
  props: {
    detail: { type: Object, default: null },
    loading: { type: Boolean, default: false },
  },
  emits: ['close'],
  computed: {
    dailyTargets() {
      if (!this.detail) return [];
      let previous = 0;
      return this.detail.daily.map((point) => {
        const target = Math.max(0, point.target_cents - previous);
        previous = point.target_cents;
        return target;
      });
    },
    chart() {
      const days = this.detail ? this.detail.daily : [];
      if (!days.length) return { bars: [], line: '', labels: [] };

      const values = days.map((d) => d.spend_cents);
      const max = Math.max(1, ...values, ...this.dailyTargets);
      const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
      const slot = (WIDTH - PAD_X * 2) / days.length;
      const barWidth = Math.max(2, slot * 0.62);

      const yFor = (value) => PAD_TOP + plotHeight * (1 - value / max);

      const bars = days.map((point, index) => {
        const value = point.spend_cents;
        const x = PAD_X + index * slot + (slot - barWidth) / 2;
        const y = yFor(value);
        return {
          key: point.day,
          x: x.toFixed(2),
          y: y.toFixed(2),
          width: barWidth.toFixed(2),
          height: Math.max(0, HEIGHT - PAD_BOTTOM - y).toFixed(2),
          over: value > this.dailyTargets[index] * 1.1,
          title: `${shortDate(point.day)} · ${moneyExact(value)} spent`,
        };
      });

      const line = days
        .map((point, index) => {
          const x = PAD_X + index * slot + slot / 2;
          return `${x.toFixed(1)},${yFor(this.dailyTargets[index]).toFixed(1)}`;
        })
        .join(' ');

      const labelIndexes = [...new Set([0, Math.floor(days.length / 2), days.length - 1])];

      return {
        bars,
        line,
        labels: labelIndexes.map((index) => ({
          x: (PAD_X + index * slot + slot / 2).toFixed(1),
          text: shortDate(days[index].day),
        })),
        baseline: HEIGHT - PAD_BOTTOM,
      };
    },
    stateLabel() {
      return this.detail ? STATE_LABELS[this.detail.state] || this.detail.state : '';
    },
  },
  methods: { money, moneyExact, percent },
  template: `
    <template v-if="detail">
      <div class="drawer-scrim" @click="$emit('close')"></div>
      <aside class="drawer" role="dialog" aria-modal="true" :aria-label="detail.campaign_name">
        <header class="drawer-head">
          <div>
            <div class="drawer-title">{{ detail.campaign_name }}</div>
            <div class="drawer-sub">
              {{ detail.channel }} · #{{ detail.campaign_id }} · {{ detail.mode.replace('_', ' ') }} pacing
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 10px">
            <span class="state" :class="detail.state">{{ stateLabel }}</span>
            <button type="button" @click="$emit('close')" aria-label="Close details">Close</button>
          </div>
        </header>

        <div class="drawer-body">
          <div class="stat-grid">
            <div class="stat">
              <div class="stat-label">Budget</div>
              <div class="stat-value">{{ money(detail.total_budget_cents) }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Spent to date</div>
              <div class="stat-value">{{ money(detail.spent_to_date_cents) }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Plan to date</div>
              <div class="stat-value">{{ money(detail.target_to_date_cents) }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Projected final</div>
              <div class="stat-value">{{ money(detail.projected_final_spend_cents) }}</div>
            </div>
            <div class="stat">
              <div class="stat-label">Projected overspend</div>
              <div class="stat-value" :style="{ color: detail.projected_overspend_cents ? 'var(--danger)' : 'inherit' }">
                {{ money(detail.projected_overspend_cents) }}
              </div>
            </div>
            <div class="stat">
              <div class="stat-label">Today left</div>
              <div class="stat-value">{{ money(detail.remaining_today_cents) }}</div>
            </div>
          </div>

          <div class="section-title">Daily delivery vs plan</div>
          <svg class="chart" :viewBox="'0 0 ' + 600 + ' 172'" role="img"
               :aria-label="'Daily spend against the pacing plan for ' + detail.campaign_name">
            <line
              v-for="bar in chart.bars"
              :key="bar.key"
              :x1="bar.x"
              :x2="bar.x"
              :y1="10"
              :y2="chart.baseline"
              stroke="#16202b"
              stroke-width="0.5"
            />
            <rect
              v-for="bar in chart.bars"
              :key="bar.key + '-bar'"
              :x="bar.x"
              :y="bar.y"
              :width="bar.width"
              :height="bar.height"
              :fill="bar.over ? '#f87171' : '#2dd4bf'"
              opacity="0.85"
              rx="1.5"
            >
              <title>{{ bar.title }}</title>
            </rect>
            <polyline :points="chart.line" fill="none" stroke="#d7e2ee" stroke-width="1.2"
                      stroke-dasharray="4 3" opacity="0.7" />
            <text
              v-for="label in chart.labels"
              :key="label.text"
              :x="label.x"
              y="166"
              fill="#5b6878"
              font-size="9"
              text-anchor="middle"
              font-family="ui-monospace, monospace"
            >{{ label.text }}</text>
          </svg>
          <div class="chart-legend">
            <span class="legend-key"><span class="legend-swatch"></span> actual spend</span>
            <span class="legend-key"><span class="legend-swatch target"></span> plan</span>
            <span class="legend-key" style="margin-left: auto">flight day {{ detail.flight_day }}/{{ detail.flight_days }}</span>
          </div>

          <div class="section-title">Budget changes</div>
          <ul v-if="detail.budget_changes.length" class="audit-list">
            <li v-for="change in detail.budget_changes" :key="change.id">
              <span>{{ money(Number(change.before_value)) }} → {{ money(Number(change.after_value)) }}</span>
              <span style="color: var(--faint)">{{ change.actor }}</span>
            </li>
          </ul>
          <div v-else class="empty" style="padding: 14px">No budget changes recorded.</div>
        </div>
      </aside>
    </template>
  `,
};
