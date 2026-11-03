// REAL-TIME DATASETS WITH FULL STOCK METRICS
const MARKET_DATASETS = {
  "BTC/USD": { name: "Bitcoin", price: 67420.50, change: "+3.4%", positive: true, volume: "$28.4B", mcap: "$1.32T", high24: "$68,100", low24: "$65,200", pe: "N/A" },
  "ETH/USD": { name: "Ethereum", price: 3510.20, change: "+1.8%", positive: true, volume: "$14.2B", mcap: "$420B", high24: "$3,580", low24: "$3,410", pe: "N/A" },
  "NVDA": { name: "NVIDIA Corp.", price: 124.80, change: "-0.6%", positive: false, volume: "$8.9B", mcap: "$3.06T", high24: "$127.40", low24: "$123.10", pe: "72.4" },
  "AAPL": { name: "Apple Inc.", price: 224.30, change: "+0.9%", positive: true, volume: "$6.1B", mcap: "$3.44T", high24: "$226.00", low24: "$221.80", pe: "34.1" }
};

// INITIALIZE STORED ORDERS
let ordersDataset = JSON.parse(localStorage.getItem("apex_orders")) || [
  { id: "ORD-94821", time: "2026-07-22 20:45:12", asset: "BTC", side: "BUY", qty: 0.45, price: 67200, fee: 30.24, status: "Settled" },
  { id: "ORD-94820", time: "2026-07-22 19:30:00", asset: "NVDA", side: "BUY", qty: 25.0, price: 122.50, fee: 3.06, status: "Settled" },
  { id: "ORD-94819", time: "2026-07-22 18:15:42", asset: "ETH", side: "SELL", qty: 2.10, price: 3500.00, fee: 7.35, status: "Settled" }
];

document.addEventListener("DOMContentLoaded", () => {
  const page = window.location.pathname.split("/").pop();
  const user = localStorage.getItem("apex_user");

  if (!user && page !== "index.html" && page !== "") {
    window.location.href = "index.html";
    return;
  }

  const userDisplay = document.getElementById("userDisplay");
  if (userDisplay && user) userDisplay.innerText = user;

  if (page === "dashboard.html" || page === "") {
    renderMarketCards();
    renderDashboardTable();
    initChart();
  } else if (page === "holdings.html") {
    renderHoldingsTable();
  } else if (page === "transactions.html") {
    renderFullOrderTable();
  }

  const txForm = document.getElementById("txForm");
  if (txForm) txForm.addEventListener("submit", handleTradeSubmit);
});

// RENDER TICKER CARDS WITH POPUP CLICK HANDLER
function renderMarketCards() {
  const container = document.getElementById("marketCards");
  if (!container) return;

  container.innerHTML = Object.keys(MARKET_DATASETS).map(symbol => {
    const item = MARKET_DATASETS[symbol];
    return `
      <div onclick="openStockModal('${symbol}')" class="glass-card p-5 rounded-3xl cursor-pointer hover:-translate-y-1 transition duration-300">
        <div class="flex justify-between items-center mb-3">
          <span class="text-xs font-mono-code font-bold text-slate-400">${symbol}</span>
          <span class="text-[11px] font-mono-code font-extrabold px-2.5 py-1 rounded-xl ${
            item.positive ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
          }">${item.change}</span>
        </div>
        <div class="text-2xl font-black text-white">$${item.price.toLocaleString()}</div>
        <div class="flex justify-between items-center mt-2 text-[11px] text-slate-500">
          <span>${item.name}</span>
          <span class="font-mono-code text-indigo-400">Click for info 🔍</span>
        </div>
      </div>
    `;
  }).join('');
}

// STOCK MODAL POPUP
function openStockModal(symbol) {
  const item = MARKET_DATASETS[symbol];
  if (!item) return;

  const modal = document.getElementById("stockModal");
  const modalContent = document.getElementById("modalContent");

  modalContent.innerHTML = `
    <div class="flex items-center gap-3 mb-4">
      <div class="w-12 h-12 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center font-bold text-indigo-400 text-lg">${symbol.substring(0,3)}</div>
      <div>
        <h3 class="text-xl font-extrabold text-white">${item.name} (${symbol})</h3>
        <p class="text-xs text-slate-400">Detailed Institutional Asset Metrics</p>
      </div>
    </div>
    <div class="grid grid-cols-2 gap-3 mb-6 font-mono-code text-xs">
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">Current Price</span><strong class="text-white text-sm">$${item.price.toLocaleString()}</strong></div>
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">24h Change</span><strong class="${item.positive ? 'text-emerald-400' : 'text-rose-400'} text-sm">${item.change}</strong></div>
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">Market Cap</span><strong class="text-white">${item.mcap}</strong></div>
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">24h Volume</span><strong class="text-white">${item.volume}</strong></div>
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">24h High</span><strong class="text-emerald-400">${item.high24}</strong></div>
      <div class="bg-slate-950/60 p-3 rounded-xl border border-slate-800"><span class="text-slate-500 block">24h Low</span><strong class="text-rose-400">${item.low24}</strong></div>
    </div>
    <button onclick="fillQuickTrade('${symbol}', ${item.price})" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-extrabold py-3 rounded-xl transition text-xs">
      Quick Load Trade Panel
    </button>
  `;

  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeModal() {
  const modal = document.getElementById("stockModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function fillQuickTrade(symbol, price) {
  document.getElementById("assetSymbol").value = symbol.replace("/USD", "");
  document.getElementById("assetPrice").value = price;
  closeModal();
}

// HANDLE TRADE & REDIRECT TO HOLDINGS
function handleTradeSubmit(e) {
  e.preventDefault();
  const asset = document.getElementById("assetSymbol").value.toUpperCase();
  const qty = parseFloat(document.getElementById("assetQty").value);
  const price = parseFloat(document.getElementById("assetPrice").value);
  const side = document.getElementById("txType").value;

  const newOrder = {
    id: `ORD-${Math.floor(10000 + Math.random() * 90000)}`,
    time: new Date().toISOString().replace("T", " ").substring(0, 19),
    asset,
    side,
    qty,
    price,
    fee: Number((qty * price * 0.001).toFixed(2)),
    status: "Settled"
  };

  ordersDataset.unshift(newOrder);
  localStorage.setItem("apex_orders", JSON.stringify(ordersDataset));

  // Redirect directly to My Holdings Page
  window.location.href = "holdings.html";
}

// RENDER HOLDINGS PAGE TABLE
function renderHoldingsTable() {
  const tbody = document.getElementById("holdingsTableBody");
  if (!tbody) return;

  const buyOrders = ordersDataset.filter(o => o.side === "BUY");
  
  if (buyOrders.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" class="py-6 text-center text-slate-500">No active stock holdings yet. Execute a trade to see positions here!</td></tr>`;
    return;
  }

  tbody.innerHTML = buyOrders.map(tx => {
    const val = tx.qty * tx.price;
    return `
      <tr class="hover:bg-slate-800/40 transition">
        <td class="py-4 px-5 font-extrabold text-white text-sm">${tx.asset}</td>
        <td class="py-4 px-5 font-mono-code"><span class="px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400">LONG</span></td>
        <td class="py-4 px-5 font-mono-code">${tx.qty}</td>
        <td class="py-4 px-5 font-mono-code">$${tx.price.toLocaleString()}</td>
        <td class="py-4 px-5 font-mono-code font-bold text-white">$${val.toLocaleString()}</td>
        <td class="py-4 px-5 font-mono-code text-emerald-400 font-bold">+$${(val * 0.025).toFixed(2)} (+2.5%)</td>
        <td class="py-4 px-5 font-mono-code"><span class="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400">Active</span></td>
      </tr>
    `;
  }).join('');
}

// RENDER DASHBOARD RECENT TABLE
function renderDashboardTable() {
  const tbody = document.getElementById("dashboardTxTable");
  if (!tbody) return;

  tbody.innerHTML = ordersDataset.slice(0, 4).map(tx => `
    <tr class="hover:bg-slate-800/30 transition">
      <td class="py-3.5 px-5 font-mono-code text-indigo-400 font-bold">${tx.id}</td>
      <td class="py-3.5 px-5 font-mono-code text-slate-400">${tx.time.split(" ")[1]}</td>
      <td class="py-3.5 px-5 font-extrabold text-white">${tx.asset}</td>
      <td class="py-3.5 px-5"><span class="text-[10px] font-mono-code font-extrabold px-2 py-1 rounded ${tx.side === 'BUY' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}">${tx.side}</span></td>
      <td class="py-3.5 px-5 font-mono-code">${tx.qty}</td>
      <td class="py-3.5 px-5 font-mono-code">$${tx.price.toLocaleString()}</td>
      <td class="py-3.5 px-5 font-mono-code font-bold text-white">$${(tx.qty * tx.price).toLocaleString()}</td>
      <td class="py-3.5 px-5 font-mono-code text-slate-400">$${tx.fee}</td>
      <td class="py-3.5 px-5"><span class="text-[10px] font-mono-code font-bold text-emerald-400">● ${tx.status}</span></td>
    </tr>
  `).join('');
}

function logout() {
  localStorage.removeItem("apex_user");
  window.location.href = "index.html";
}

function initChart() {
  const ctx = document.getElementById("portfolioChart");
  if (!ctx) return;
  new Chart(ctx, {
    type: 'line',
    data: {
      labels: ['09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00'],
      datasets: [{
        data: [42000, 42800, 42300, 43100, 42900, 43850, 44200],
        borderColor: '#6366f1',
        borderWidth: 3,
        fill: false,
        tension: 0.4
      }]
    },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
  });
}