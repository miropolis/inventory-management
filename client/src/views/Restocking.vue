<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="successMessage" class="notice notice-success">{{ successMessage }}</div>
    <div v-if="submitError" class="notice notice-error">{{ submitError }}</div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <label class="budget-label" for="budget-slider">{{ t('restocking.budget') }}</label>
        <input
          id="budget-slider"
          v-model.number="budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="sliderMax"
          :step="sliderStep"
        />
        <span class="budget-value">{{ formatCurrency(budget) }}</span>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatCurrency(budget) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.committed') }}</div>
          <div class="stat-value">{{ formatCurrency(committed) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatCurrency(remaining) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.title') }} ({{ funded.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="funded.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placing') : t('restocking.placeOrder') }}
          </button>
        </div>
        <div v-if="funded.length === 0" class="empty-state">{{ t('restocking.noRecommendations') }}</div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th>{{ t('restocking.table.quantity') }}</th>
                <th>{{ t('restocking.table.unitCost') }}</th>
                <th>{{ t('restocking.table.lineCost') }}</th>
                <th>{{ t('restocking.table.leadTime') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in funded" :key="item.sku">
                <td><strong>{{ item.sku }}</strong></td>
                <td>{{ item.name }}</td>
                <td>
                  <span :class="['badge', item.trend]">{{ t(`trends.${item.trend}`) }}</span>
                </td>
                <td>{{ item.quantity.toLocaleString() }}</td>
                <td>{{ formatCurrency(item.unit_cost, 2) }}</td>
                <td><strong>{{ formatCurrency(item.line_cost) }}</strong></td>
                <td>{{ t('orders.submittedOrders.days', { count: item.lead_time_days }) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

const TREND_PRIORITY = { increasing: 0, stable: 1, decreasing: 2 }

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency } = useI18n()

    const currencySymbol = computed(() => (currentCurrency.value === 'JPY' ? '¥' : '$'))

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const inventoryItems = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const successMessage = ref('')
    const submitError = ref('')

    const candidates = computed(() => {
      const bySku = new Map(inventoryItems.value.map(i => [i.sku, i]))
      const result = []
      for (const f of forecasts.value) {
        const inv = bySku.get(f.item_sku)
        if (!inv) continue
        const need = Math.max(f.forecasted_demand - inv.quantity_on_hand, 0)
        if (need <= 0) continue
        result.push({
          sku: inv.sku,
          name: inv.name,
          trend: f.trend,
          quantity: need,
          unit_cost: inv.unit_cost,
          line_cost: need * inv.unit_cost,
          lead_time_days: inv.lead_time_days || 14
        })
      }
      return result.sort((a, b) => {
        const pa = TREND_PRIORITY[a.trend] ?? 3
        const pb = TREND_PRIORITY[b.trend] ?? 3
        return pa !== pb ? pa - pb : b.quantity - a.quantity
      })
    })

    const maxBudget = computed(() => candidates.value.reduce((sum, c) => sum + c.line_cost, 0))
    const sliderStep = computed(() => (maxBudget.value < 1000 ? 1 : 100))
    // Round up to a step multiple so the top of the slider is reachable by dragging
    const sliderMax = computed(() => Math.ceil(maxBudget.value / sliderStep.value) * sliderStep.value)

    const funded = computed(() => {
      let left = budget.value
      const result = []
      for (const c of candidates.value) {
        if (c.line_cost <= left) {
          result.push(c)
          left -= c.line_cost
        }
      }
      return result
    })

    const committed = computed(() => funded.value.reduce((sum, c) => sum + c.line_cost, 0))
    const remaining = computed(() => budget.value - committed.value)

    const formatCurrency = (value, decimals = 0) => {
      return `${currencySymbol.value}${Number(value).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}`
    }

    const loadData = async () => {
      try {
        loading.value = true
        error.value = null
        const [forecastsData, inventoryData] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory({})
        ])
        forecasts.value = forecastsData
        inventoryItems.value = inventoryData
        budget.value = maxBudget.value
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (funded.value.length === 0 || submitting.value) return
      submitting.value = true
      successMessage.value = ''
      submitError.value = ''
      try {
        const order = await api.createRestockingOrder({
          items: funded.value.map(i => ({ sku: i.sku, quantity: i.quantity }))
        })
        successMessage.value = t('restocking.orderPlaced', {
          id: order.id,
          date: order.expected_delivery
        })
        await loadData()
      } catch (err) {
        console.error('Failed to place restocking order:', err)
        submitError.value = t('restocking.orderFailed')
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadData)

    return {
      t,
      loading,
      error,
      budget,
      maxBudget,
      sliderMax,
      sliderStep,
      funded,
      committed,
      remaining,
      submitting,
      successMessage,
      submitError,
      formatCurrency,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem 1.5rem;
  margin-bottom: 1.5rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.budget-slider {
  flex: 1;
  accent-color: #2563eb;
}

.budget-value {
  min-width: 110px;
  text-align: right;
  font-weight: 700;
  color: #0f172a;
}

.place-order-btn {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 6px;
  padding: 0.5rem 1rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.notice {
  padding: 0.75rem 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  font-size: 0.875rem;
}

.notice-success {
  background: #d1fae5;
  color: #065f46;
  border: 1px solid #a7f3d0;
}

.notice-error {
  background: #fee2e2;
  color: #991b1b;
  border: 1px solid #fecaca;
}
</style>
