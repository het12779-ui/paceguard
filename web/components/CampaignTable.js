import PacingBar from './PacingBar.js';
import { STATE_LABELS, money, moneyExact } from '../format.js';

export default {
  name: 'CampaignTable',
  components: { PacingBar },
  props: {
    items: { type: Array, default: () => [] },
    loading: { type: Boolean, default: false },
  },
  emits: ['select'],
  methods: {
    money,
    moneyExact,
    stateLabel(state) {
      return STATE_LABELS[state] || state;
    },
  },
  template: `
    <section class="panel" aria-labelledby="campaigns-title">
      <div class="panel-head">
        <div class="panel-title" id="campaigns-title">Campaign pacing</div>
        <div class="panel-meta">{{ items.length }} active</div>
      </div>

      <table v-if="items.length">
        <thead>
          <tr>
            <th scope="col">Campaign</th>
            <th scope="col">Budget</th>
            <th scope="col">Spent</th>
            <th scope="col" style="min-width: 170px">Pacing</th>
            <th scope="col">State</th>
            <th scope="col" title="Remaining allowance for today">Today left</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in items"
            :key="item.campaign_id"
            tabindex="0"
            role="button"
            :aria-label="'Open ' + item.campaign_name"
            @click="$emit('select', item.campaign_id)"
            @keydown.enter.prevent="$emit('select', item.campaign_id)"
            @keydown.space.prevent="$emit('select', item.campaign_id)"
          >
            <td>
              <div class="campaign-name">{{ item.campaign_name }}</div>
              <div class="campaign-id"><span class="chip">{{ item.channel }}</span> #{{ item.campaign_id }}</div>
            </td>
            <td class="num">
              {{ money(item.total_budget_cents) }}
              <div class="num-sub">{{ item.mode.replace('_', ' ') }}</div>
            </td>
            <td class="num">
              {{ money(item.spent_to_date_cents) }}
              <div class="num-sub">{{ money(item.spent_today_cents) }} today</div>
            </td>
            <td><pacing-bar :item="item" /></td>
            <td><span class="state" :class="item.state">{{ stateLabel(item.state) }}</span></td>
            <td class="num">
              {{ money(item.remaining_today_cents) }}
              <div class="num-sub">of {{ money(item.today_budget_cents) }}</div>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-else-if="loading" class="empty">
        <div class="skeleton" style="width: 60%; margin: 0 auto 10px"></div>
        <div class="skeleton" style="width: 40%; margin: 0 auto"></div>
      </div>

      <div v-else class="empty">
        <strong>No campaigns in flight</strong>
        Create one through <code>POST /api/v1/campaigns</code> or check the as-of date.
      </div>
    </section>
  `,
};
