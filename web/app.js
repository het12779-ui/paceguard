import { createApp, computed, onMounted, onUnmounted, ref } from './vendor/vue.esm-browser.prod.js';
import { api, session } from './api.js';
import { money, percent, todayISO } from './format.js';
import CampaignTable from './components/CampaignTable.js';
import AlertPanel from './components/AlertPanel.js';
import CampaignDrawer from './components/CampaignDrawer.js';

const App = {
  components: { CampaignTable, AlertPanel, CampaignDrawer },

  setup() {
    const accounts = ref([]);
    const accountId = ref(null);
    const asOf = ref(todayISO());
    const overview = ref({ totals: null, items: [] });
    const alerts = ref([]);
    const detail = ref(null);
    const error = ref('');
    const loading = ref(true);
    const evaluating = ref(false);
    const resolvingId = ref(null);
    const toast = ref('');

    let toastTimer = null;

    const totals = computed(
      () =>
        overview.value.totals || {
          campaigns: 0,
          total_budget_cents: 0,
          spent_to_date_cents: 0,
          projected_final_spend_cents: 0,
          projected_overspend_cents: 0,
          open_alerts: 0,
        },
    );

    const spentShare = computed(() =>
      totals.value.total_budget_cents
        ? totals.value.spent_to_date_cents / totals.value.total_budget_cents
        : 0,
    );

    const criticalCount = computed(
      () => alerts.value.filter((alert) => alert.severity === 'critical').length,
    );

    function notify(message) {
      toast.value = message;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => (toast.value = ''), 3200);
    }

    async function load() {
      if (!accountId.value) return;
      loading.value = true;
      session.accountId = accountId.value;
      try {
        const [pace, open] = await Promise.all([
          api.overview(asOf.value),
          api.alerts(asOf.value),
        ]);
        overview.value = pace;
        alerts.value = open;
        error.value = '';
      } catch (err) {
        error.value = err.message;
      } finally {
        loading.value = false;
      }
    }

    async function boot() {
      try {
        accounts.value = await api.accounts();
        if (!accounts.value.length) {
          error.value =
            'Demo tenant switching is disabled. Set PACEGUARD_DEMO=1 for the standalone demo.';
          return;
        }
        accountId.value = accounts.value[0].id;
        session.accountId = accountId.value;
        await load();
      } catch (err) {
        error.value = err.message;
      } finally {
        loading.value = false;
      }
    }

    async function openCampaign(campaignId) {
      try {
        detail.value = await api.campaign(campaignId, asOf.value);
      } catch (err) {
        notify(err.message);
      }
    }

    async function evaluate() {
      evaluating.value = true;
      try {
        const result = await api.evaluate(asOf.value);
        await load();
        notify(
          result.alerts_created > 0
            ? `${result.alerts_created} new guardrail alert${result.alerts_created === 1 ? '' : 's'}`
            : 'Guardrails evaluated — nothing new',
        );
      } catch (err) {
        error.value = err.message;
      } finally {
        evaluating.value = false;
      }
    }

    async function resolveAlert(alertId) {
      resolvingId.value = alertId;
      try {
        await api.resolveAlert(alertId);
        alerts.value = alerts.value.filter((alert) => alert.id !== alertId);
        if (overview.value.totals) overview.value.totals.open_alerts -= 1;
        notify('Alert resolved');
      } catch (err) {
        notify(err.message);
      } finally {
        resolvingId.value = null;
      }
    }

    function onKeydown(event) {
      if (event.key === 'Escape') detail.value = null;
    }

    onMounted(() => {
      window.addEventListener('keydown', onKeydown);
      boot();
    });

    onUnmounted(() => {
      window.removeEventListener('keydown', onKeydown);
      clearTimeout(toastTimer);
    });

    return {
      accounts,
      accountId,
      asOf,
      overview,
      alerts,
      detail,
      error,
      loading,
      evaluating,
      resolvingId,
      toast,
      totals,
      spentShare,
      criticalCount,
      load,
      evaluate,
      openCampaign,
      resolveAlert,
      money,
      percent,
    };
  },

  template: `
    <div :class="{ loading }">
      <header class="topbar">
        <div class="brand">
          <div class="brand-mark">PG</div>
          <div>
            <div class="brand-name">PaceGuard</div>
            <div class="brand-sub">Budget pacing &amp; spend governance</div>
          </div>
        </div>

        <div class="controls">
          <label class="field">
            <span>Account</span>
            <select v-model.number="accountId" @change="load" aria-label="Account">
              <option v-for="account in accounts" :key="account.id" :value="account.id">
                {{ account.name }}
              </option>
            </select>
          </label>
          <label class="field">
            <span>As of</span>
            <input type="date" v-model="asOf" @change="load" aria-label="As of date" />
          </label>
          <button class="primary" type="button" :disabled="evaluating" @click="evaluate">
            {{ evaluating ? 'Evaluating…' : 'Evaluate guardrails' }}
          </button>
        </div>
      </header>

      <main>
        <div v-if="error" class="banner">
          <span>{{ error }}</span>
          <button type="button" @click="load">Retry</button>
        </div>

        <section class="kpis" aria-label="Account totals">
          <div class="kpi">
            <div class="kpi-label">Budget in flight</div>
            <div class="kpi-value">{{ money(totals.total_budget_cents) }}</div>
            <div class="kpi-foot">{{ totals.campaigns }} campaigns</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Spent to date</div>
            <div class="kpi-value">{{ money(totals.spent_to_date_cents) }}</div>
            <div class="kpi-foot">{{ percent(spentShare, 1) }} of budget</div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Projected final spend</div>
            <div class="kpi-value">{{ money(totals.projected_final_spend_cents) }}</div>
            <div
              class="kpi-foot"
              :class="totals.projected_overspend_cents ? 'is-danger' : 'is-ok'"
            >
              {{ totals.projected_overspend_cents
                ? money(totals.projected_overspend_cents) + ' over plan'
                : 'within budget' }}
            </div>
          </div>
          <div class="kpi">
            <div class="kpi-label">Open guardrails</div>
            <div class="kpi-value">{{ alerts.length }}</div>
            <div class="kpi-foot" :class="criticalCount ? 'is-danger' : 'is-ok'">
              {{ criticalCount ? criticalCount + ' critical' : 'nothing critical' }}
            </div>
          </div>
        </section>

        <div class="grid">
          <campaign-table
            :items="overview.items"
            :loading="loading"
            @select="openCampaign"
          />
          <alert-panel
            :alerts="alerts"
            :resolving-id="resolvingId"
            @resolve="resolveAlert"
          />
        </div>
      </main>

      <campaign-drawer :detail="detail" @close="detail = null" />
      <div v-if="toast" class="toast" role="status">{{ toast }}</div>
    </div>
  `,
};

createApp(App).mount('#app');
