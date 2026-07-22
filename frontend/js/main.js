const API_URL = "http://127.0.0.1:8000/api";
let allocationChartInstance = null;
let simChartInstance = null;

const CURRENCY_RATES = { USD: 1.0, EUR: 0.92, INR: 83.5 };
const CURRENCY_SYMBOLS = { USD: "$", EUR: "€", INR: "₹" };
let currentCurrency = "USD";
let rawPortfolioData = null;

// ================= AUTHENTICATION LOGIC =================
function checkAuth() {
  const isLoggedIn = localStorage.getItem("apex_user_logged_in");
  const authSection = document.getElementById("page-auth");
  const mainApp = document.getElementById("mainApp");

  if (isLoggedIn === "true") {
    authSection.classList.add("hidden");
    mainApp.classList.remove("hidden");
    fetchPortfolio();
  } else {
    authSection.classList.remove("hidden");
    mainApp.classList.add("hidden");
  }
}

// Login Submit Listener
document.getElementById("loginForm").addEventListener("submit", (e) => {
  e.preventDefault();
  localStorage.setItem("apex_user_logged_in", "true");
  checkAuth();
});

// Logout Button Listener
document.getElementById("logoutBtn").addEventListener("click", () => {
  localStorage.removeItem("apex_user_logged_in");
  checkAuth();
});

// ================= SPA TAB SWITCHER =================
function switchTab(tabName) {
  ['dashboard', 'trade', 'simulator', 'history'].forEach(t => {
    document.getElementById(`page-${t}`).classList.add('hidden');
    const tabBtn = document.getElementById(`tab-${t}`);
    tabBtn.classList.remove('bg-blue-600', 'text-white');
    tabBtn.classList.add('text-slate-400');
  });

  document.getElementById(`page-${tabName}`).classList.remove('hidden');
  const activeBtn = document.getElementById(`tab-${tabName}`);
  activeBtn.classList.add('bg-blue-600', 'text-white');
  activeBtn.classList.remove('text-slate-400');

  if (tabName === 'simulator') runSimulator();
}

// Fetch Portfolio Data
async function fetchPortfolio() {
  try {
    const res = await fetch(`${API_URL}/portfolio/summary`);
    rawPortfolioData = await res.json();
    renderDashboard();
    renderAuditHistory();
  } catch (err) {
    console.error("Error fetching data:", err);
  }
}

function renderDashboard() {
  if (!rawPortfolioData) return;

  const rate = CURRENCY_RATES[currentCurrency];
  const sym = CURRENCY_SYMBOLS[currentCurrency];

  const totalVal = rawPortfolioData.total_value * rate;
  const totalInv = rawPortfolioData.total_invested * rate;
  const totalPL = rawPortfolioData.total_profit_loss * rate;

  document.getElementById("netWorth").innerText = `${sym}${totalVal.toLocaleString('en-US', {minimumFractionDigits: 2})}`;
  document.getElementById("totalInvested").innerText = `${sym}${totalInv.toLocaleString('en-US', {minimumFractionDigits: 2})}`;

  const plEl = document.getElementById("totalPL");
  const isProfit = totalPL >= 0;
  plEl.innerText = `${sym}${totalPL.toLocaleString('en-US', {minimumFractionDigits: 2})} (${rawPortfolioData.total_profit_loss_pct}%)`;
  plEl.className = `text-3xl font-extrabold ${isProfit ? 'text-emerald-400' : 'text-rose-500'}`;

  calculateRiskScore(rawPortfolioData.holdings, totalVal);

  const tbody = document.getElementById("holdingsTable");
  tbody.innerHTML = "";
  const labels = [];
  const values = [];

  if (rawPortfolioData.holdings.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="px-4 py-6 text-center text-slate-500">No assets found. Execute your first order in the Trade Execution tab!</td></tr>`;
  }

  rawPortfolioData.holdings.forEach(h => {
    const hVal = h.current_value * rate;
    const hPrice = h.current_price * rate;
    const hAvg = h.avg_buy_price * rate;
    const hPL = h.profit_loss * rate;

    labels.push(h.symbol);
    values.push(hVal);

    const isAssetProfit = hPL >= 0;
    const row = `<tr class="hover:bg-slate-800/30 transition-colors">
      <td class="px-4 py-3.5 font-bold text-white">${h.symbol} <span class="text-xs font-normal text-slate-500">(${h.name})</span></td>
      <td class="px-4 py-3.5"><span class="px-2 py-0.5 text-xs rounded-md ${h.asset_type === 'crypto' ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'}">${h.asset_type.toUpperCase()}</span></td>
      <td class="px-4 py-3.5">${h.total_quantity}</td>
      <td class="px-4 py-3.5">${sym}${hAvg.toLocaleString()}</td>
      <td class="px-4 py-3.5 font-medium">${sym}${hPrice.toLocaleString()}</td>
      <td class="px-4 py-3.5 font-bold text-white">${sym}${hVal.toLocaleString()}</td>
      <td class="px-4 py-3.5 font-semibold ${isAssetProfit ? 'text-emerald-400' : 'text-rose-500'}">${isAssetProfit ? '+' : ''}${sym}${hPL.toLocaleString()} (${h.profit_loss_pct}%)</td>
    </tr>`;
    tbody.innerHTML += row;
  });

  renderAllocationChart(labels, values);
}

function calculateRiskScore(holdings, totalVal) {
  const scoreEl = document.getElementById("riskScore");
  const badgeEl = document.getElementById("riskBadge");

  if (!holdings || holdings.length === 0 || totalVal === 0) {
    scoreEl.innerText = "N/A";
    badgeEl.innerText = "No Data";
    return;
  }

  let maxConcentration = 0;
  holdings.forEach(h => {
    const pct = (h.current_value / (totalVal / CURRENCY_RATES[currentCurrency])) * 100;
    if (pct > maxConcentration) maxConcentration = pct;
  });

  let score = Math.round(100 - maxConcentration + (holdings.length * 5));
  if (score > 100) score = 98;
  if (score < 15) score = 15;

  scoreEl.innerText = `${score}/100`;

  if (score > 70) {
    scoreEl.className = "text-3xl font-extrabold text-emerald-400";
    badgeEl.innerText = "Optimal Balance";
    badgeEl.className = "px-2.5 py-1 text-xs rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-semibold";
  } else {
    scoreEl.className = "text-3xl font-extrabold text-amber-400";
    badgeEl.innerText = "High Concentration";
    badgeEl.className = "px-2.5 py-1 text-xs rounded-md bg-amber-500/10 text-amber-400 border border-amber-500/20 font-semibold";
  }
}

function renderAuditHistory() {
  const tbody = document.getElementById("historyTable");
  if (!rawPortfolioData || !rawPortfolioData.holdings) return;

  tbody.innerHTML = "";
  const rate = CURRENCY_RATES[currentCurrency];
  const sym = CURRENCY_SYMBOLS[currentCurrency];

  rawPortfolioData.holdings.forEach(h => {
    const totalSpent = h.total_quantity * h.avg_buy_price * rate;
    const row = `<tr class="hover:bg-slate-800/30 transition-colors">
      <td class="px-4 py-3 font-bold text-white">${h.symbol}</td>
      <td class="px-4 py-3 uppercase text-xs text-slate-400">${h.asset_type}</td>
      <td class="px-4 py-3"><span class="px-2 py-0.5 text-xs rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-bold">BUY</span></td>
      <td class="px-4 py-3">${h.total_quantity}</td>
      <td class="px-4 py-3">${sym}${(h.avg_buy_price * rate).toLocaleString()}</td>
      <td class="px-4 py-3 font-bold text-white">${sym}${totalSpent.toLocaleString()}</td>
    </tr>`;
    tbody.innerHTML += row;
  });
}

function runSimulator() {
  const monthly = parseFloat(document.getElementById("simMonthly").value) || 0;
  const years = parseFloat(document.getElementById("simYears").value) || 0;
  const annualReturn = parseFloat(document.getElementById("simReturn").value) || 0;

  const labels = [];
  const projectedData = [];
  const investedData = [];

  const monthlyRate = (annualReturn / 100) / 12;
  let currentBalance = 0;
  let totalDeposited = 0;

  for (let year = 1; year <= years; year++) {
    labels.push(`Year ${year}`);
    for (let month = 0; month < 12; month++) {
      currentBalance = (currentBalance + monthly) * (1 + monthlyRate);
      totalDeposited += monthly;
    }
    projectedData.push(currentBalance * CURRENCY_RATES[currentCurrency]);
    investedData.push(totalDeposited * CURRENCY_RATES[currentCurrency]);
  }

  const sym = CURRENCY_SYMBOLS[currentCurrency];
  document.getElementById("simResult").innerText = `${sym}${projectedData[projectedData.length - 1]?.toLocaleString('en-US', {maximumFractionDigits: 2}) || 0}`;

  const ctx = document.getElementById('simChart').getContext('2d');
  if (simChartInstance) simChartInstance.destroy();

  simChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        { label: 'Projected Wealth', data: projectedData, borderColor: '#3b82f6', backgroundColor: 'rgba(59, 130, 246, 0.1)', fill: true, tension: 0.3 },
        { label: 'Total Principal Invested', data: investedData, borderColor: '#64748b', borderDash: [5, 5], fill: false }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#94a3b8' } } },
      scales: {
        x: { ticks: { color: '#64748b' }, grid: { display: false } },
        y: { ticks: { color: '#64748b' }, grid: { color: '#1e293b' } }
      }
    }
  });
}

function renderAllocationChart(labels, data) {
  const ctx = document.getElementById('allocationChart').getContext('2d');
  if (allocationChartInstance) allocationChartInstance.destroy();

  allocationChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: labels,
      datasets: [{
        data: data,
        backgroundColor: ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8' } } }
    }
  });
}

function quickFill(symbol, name, type, price) {
  document.getElementById("symbol").value = symbol;
  document.getElementById("name").value = name;
  document.getElementById("assetType").value = type;
  document.getElementById("price").value = price;
  document.getElementById("quantity").value = 1;
}

document.getElementById("currencySelect").addEventListener("change", (e) => {
  currentCurrency = e.target.value;
  renderDashboard();
  renderAuditHistory();
  runSimulator();
});

['simMonthly', 'simYears', 'simReturn'].forEach(id => {
  document.getElementById(id).addEventListener('input', runSimulator);
});

document.getElementById("txForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    asset_symbol: document.getElementById("symbol").value,
    asset_name: document.getElementById("name").value,
    asset_type: document.getElementById("assetType").value,
    transaction_type: document.getElementById("txType").value,
    quantity: parseFloat(document.getElementById("quantity").value),
    purchase_price: parseFloat(document.getElementById("price").value)
  };

  await fetch(`${API_URL}/transactions/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  e.target.reset();
  await fetchPortfolio();
  switchTab('dashboard');
});

document.getElementById("exportCsvBtn").addEventListener("click", () => {
  if (!rawPortfolioData || !rawPortfolioData.holdings) return;
  let csv = "Symbol,Name,Type,Quantity,Avg Buy Price,Current Price,Value,Profit Loss\n";
  rawPortfolioData.holdings.forEach(h => {
    csv += `${h.symbol},${h.name},${h.asset_type},${h.total_quantity},${h.avg_buy_price},${h.current_price},${h.current_value},${h.profit_loss}\n`;
  });

  const blob = new Blob([csv], { type: 'text/csv' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `apex_portfolio_audit.csv`;
  a.click();
});

// Initial Setup
checkAuth();
setInterval(() => {
  if (localStorage.getItem("apex_user_logged_in") === "true") {
    fetchPortfolio();
  }
}, 15000);