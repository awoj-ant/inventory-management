<template>
  <div class="restocking">
    <div class="page-header">
      <h2>Restocking</h2>
      <p class="page-subtitle">Budget-based demand restocking recommendations</p>
    </div>

    <div v-if="loading" class="loading">Loading...</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>

      <!-- Controls Card -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Restocking Controls</h3>
        </div>
        <div class="controls-row">
          <div class="budget-section">
            <label class="control-label">
              Available Budget: ${{ budget.toLocaleString() }}
            </label>
            <input
              type="range"
              :min="0"
              :max="totalCostAllItems"
              :step="1000"
              v-model.number="budget"
              class="budget-slider"
            />
            <div class="control-hint">Max: ${{ totalCostAllItems.toLocaleString() }} (full restock cost)</div>
          </div>

          <div class="lead-time-section">
            <label class="control-label">Delivery Lead Time</label>
            <div class="lead-time-input-row">
              <input
                type="number"
                v-model.number="leadTimeDays"
                :min="1"
                :max="365"
                class="lead-time-input"
              />
              <span class="control-unit">days</span>
            </div>
            <div class="control-hint">Expected delivery: {{ expectedDeliveryDate }}</div>
          </div>
        </div>
      </div>

      <!-- Stat Cards -->
      <div class="stats-grid restocking-stats">
        <div class="stat-card">
          <div class="stat-label">Items Selected</div>
          <div class="stat-value">
            {{ selectedItems.length }}
            <span class="stat-of-total">/ {{ allRecommendedItems.length }}</span>
          </div>
        </div>
        <div class="stat-card info">
          <div class="stat-label">Budget Used</div>
          <div class="stat-value">${{ selectedCost.toLocaleString() }}</div>
        </div>
        <div class="stat-card" :class="remainingBudget < 0 ? 'danger' : 'success'">
          <div class="stat-label">Remaining Budget</div>
          <div class="stat-value">${{ remainingBudget.toLocaleString() }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Expected Delivery</div>
          <div class="stat-value stat-value--sm">{{ expectedDeliveryDate }}</div>
        </div>
      </div>

      <!-- Recommendations Table -->
      <div class="card">
        <div class="card-header">
          <h3 class="card-title">
            Recommended Items ({{ allRecommendedItems.length }} available, {{ selectedItems.length }} within budget)
          </h3>
        </div>

        <div v-if="allRecommendedItems.length === 0" class="empty-state">
          No items require restocking based on demand forecasts.
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>Status</th>
                <th>SKU</th>
                <th>Item Name</th>
                <th>Current Demand</th>
                <th>Forecasted Demand</th>
                <th>Restock Qty</th>
                <th>Unit Cost</th>
                <th>Item Total</th>
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in allRecommendedItems"
                :key="item.sku"
                :class="{
                  'within-budget': selectedSkuSet.has(item.sku),
                  'over-budget': !selectedSkuSet.has(item.sku)
                }"
              >
                <td>
                  <span v-if="selectedSkuSet.has(item.sku)" class="badge success">In Budget</span>
                  <span v-else class="badge neutral">Over Budget</span>
                </td>
                <td><strong class="sku-text">{{ item.sku }}</strong></td>
                <td>{{ item.name }}</td>
                <td>{{ item.current_demand.toLocaleString() }}</td>
                <td><strong>{{ item.forecasted_demand.toLocaleString() }}</strong></td>
                <td><strong class="restock-qty">+{{ item.restock_qty.toLocaleString() }}</strong></td>
                <td>${{ item.unit_cost.toFixed(2) }}</td>
                <td><strong>${{ item.item_total.toLocaleString() }}</strong></td>
                <td>
                  <span :class="['badge', item.trend]">{{ item.trend }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Place Order Section -->
      <div class="place-order-section">
        <button
          class="btn-primary"
          @click="placeOrder"
          :disabled="selectedItems.length === 0 || isSubmitting"
        >
          {{ isSubmitting ? 'Placing Order...' : `Place Restocking Order (${selectedItems.length} items, $${selectedCost.toLocaleString()})` }}
        </button>
        <p v-if="orderSuccess" class="success-message">
          Order {{ lastOrderNumber }} placed successfully. View it in the Orders tab.
        </p>
        <p v-if="orderError" class="error-message">{{ orderError }}</p>
      </div>

    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted, nextTick } from 'vue'
import { api } from '../api'

export default {
  name: 'Restocking',
  setup() {
    // Raw data refs
    const demandForecasts = ref([])
    const inventoryItems = ref([])
    const loading = ref(true)
    const error = ref(null)

    // Budget / lead time controls
    const budget = ref(0)
    const leadTimeDays = ref(14)

    // Order submission state
    const isSubmitting = ref(false)
    const orderSuccess = ref(false)
    const lastOrderNumber = ref('')
    const orderError = ref(null)

    // O(1) lookup: sku -> { unit_cost, ... }
    const inventoryMap = computed(() => {
      const map = {}
      for (const item of inventoryItems.value) {
        map[item.sku] = item
      }
      return map
    })

    // Items that have a positive restock gap and a known unit cost, sorted by forecasted_demand DESC
    const allRecommendedItems = computed(() => {
      const map = inventoryMap.value
      return demandForecasts.value
        .filter(f => {
          const inv = map[f.item_sku]
          return inv && (f.forecasted_demand - f.current_demand) > 0
        })
        .map(f => {
          const inv = map[f.item_sku]
          const restock_qty = f.forecasted_demand - f.current_demand
          const unit_cost = inv.unit_cost
          return {
            sku: f.item_sku,
            name: f.item_name,
            current_demand: f.current_demand,
            forecasted_demand: f.forecasted_demand,
            trend: f.trend,
            restock_qty,
            unit_cost,
            item_total: restock_qty * unit_cost
          }
        })
        .sort((a, b) => b.forecasted_demand - a.forecasted_demand)
    })

    // Sum of all item totals — used as the slider max and initial budget
    const totalCostAllItems = computed(() => {
      return allRecommendedItems.value.reduce((sum, item) => sum + item.item_total, 0)
    })

    // Greedy selection: pick items (highest forecasted demand first) that fit remaining budget
    const selectedItems = computed(() => {
      let remaining = budget.value
      const selected = []
      for (const item of allRecommendedItems.value) {
        if (item.item_total <= remaining) {
          selected.push(item)
          remaining -= item.item_total
        }
        // Continue — a cheaper later item might still fit
      }
      return selected
    })

    const selectedCost = computed(() => {
      return selectedItems.value.reduce((sum, item) => sum + item.item_total, 0)
    })

    const remainingBudget = computed(() => budget.value - selectedCost.value)

    // Set for O(1) in-budget membership check in template
    const selectedSkuSet = computed(() => new Set(selectedItems.value.map(i => i.sku)))

    // Delivery date: today + leadTimeDays, formatted as "Mar 16, 2026"
    const expectedDeliveryDate = computed(() => {
      const date = new Date()
      date.setDate(date.getDate() + leadTimeDays.value)
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    })

    const loadData = async () => {
      loading.value = true
      error.value = null
      try {
        const [forecasts, inventory] = await Promise.all([
          api.getDemandForecasts(),
          api.getInventory()   // no filters — full inventory for unit_cost lookup
        ])
        demandForecasts.value = forecasts
        inventoryItems.value = inventory
        // Set initial budget to the full restock cost once computed values are ready
        await nextTick()
        budget.value = totalCostAllItems.value
      } catch (err) {
        error.value = 'Failed to load restocking data: ' + (err.message || 'Unknown error')
        console.error(err)
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (selectedItems.value.length === 0) return
      orderError.value = null
      orderSuccess.value = false
      isSubmitting.value = true
      try {
        const payload = {
          lead_time_days: leadTimeDays.value,
          items: selectedItems.value.map(i => ({
            sku: i.sku,
            name: i.name,
            quantity: i.restock_qty,
            unit_cost: i.unit_cost
          }))
        }
        const result = await api.createRestockingOrder(payload)
        lastOrderNumber.value = result.order_number
        orderSuccess.value = true
      } catch (err) {
        orderError.value = 'Failed to place order: ' + (err.response?.data?.detail || err.message)
      } finally {
        isSubmitting.value = false
      }
    }

    onMounted(loadData)

    return {
      // state
      loading,
      error,
      budget,
      leadTimeDays,
      isSubmitting,
      orderSuccess,
      lastOrderNumber,
      orderError,
      // computed
      allRecommendedItems,
      totalCostAllItems,
      selectedItems,
      selectedCost,
      remainingBudget,
      selectedSkuSet,
      expectedDeliveryDate,
      // methods
      placeOrder
    }
  }
}
</script>

<style scoped>
.restocking {
  /* inherits main-content padding from App.vue */
}

/* ---- Controls Card ---- */
.controls-row {
  display: flex;
  gap: 3rem;
  align-items: flex-start;
  flex-wrap: wrap;
}

.budget-section {
  flex: 1;
  min-width: 260px;
}

.lead-time-section {
  min-width: 200px;
}

.control-label {
  display: block;
  font-size: 0.875rem;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 0.625rem;
}

.budget-slider {
  width: 100%;
  height: 6px;
  cursor: pointer;
  accent-color: #2563eb;
  margin-bottom: 0.375rem;
}

.lead-time-input-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.lead-time-input {
  width: 80px;
  padding: 0.375rem 0.625rem;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 0.875rem;
  color: #0f172a;
  background: #fff;
}

.lead-time-input:focus {
  outline: none;
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.15);
}

.control-unit {
  font-size: 0.875rem;
  color: #64748b;
}

.control-hint {
  font-size: 0.813rem;
  color: #64748b;
}

/* ---- Stat Cards ---- */
.restocking-stats {
  grid-template-columns: repeat(4, 1fr);
}

/* Smaller font for longer text values (e.g. date) */
.stat-value--sm {
  font-size: 1.375rem;
}

.stat-of-total {
  font-size: 1rem;
  font-weight: 400;
  color: #64748b;
  margin-left: 0.25rem;
}

/* ---- Table Row States ---- */
.within-budget {
  /* normal row — inherits default table styles */
}

.over-budget {
  opacity: 0.45;
}

/* Monospace SKU */
.sku-text {
  font-family: 'SFMono-Regular', 'Consolas', 'Liberation Mono', monospace;
  font-size: 0.813rem;
  color: #334155;
}

/* Restock qty highlight */
.restock-qty {
  color: #2563eb;
}

/* Neutral badge (over-budget status) */
.badge.neutral {
  background: #f1f5f9;
  color: #64748b;
}

/* ---- Empty State ---- */
.empty-state {
  padding: 3rem;
  text-align: center;
  color: #64748b;
  font-size: 0.938rem;
}

/* ---- Place Order Section ---- */
.place-order-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.75rem;
  margin-top: 0.5rem;
  margin-bottom: 2rem;
}

.btn-primary {
  padding: 0.75rem 1.5rem;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 0.938rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s ease, opacity 0.2s ease;
}

.btn-primary:hover:not(:disabled) {
  background: #1d4ed8;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.success-message {
  font-size: 0.875rem;
  font-weight: 500;
  color: #065f46;
}

.error-message {
  font-size: 0.875rem;
  font-weight: 500;
  color: #991b1b;
}

/* ---- Responsive ---- */
@media (max-width: 900px) {
  .restocking-stats {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 560px) {
  .restocking-stats {
    grid-template-columns: 1fr;
  }

  .controls-row {
    flex-direction: column;
    gap: 1.5rem;
  }
}
</style>
