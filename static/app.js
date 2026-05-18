const statusEl = document.querySelector("#status");
const form = document.querySelector("#tradeForm");
const formMessage = document.querySelector("#formMessage");
const refreshButton = document.querySelector("#refreshButton");
const tradesBody = document.querySelector("#tradesBody");

const formatMoney = (value) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(value);

const formatNumber = (value) =>
  new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "Request failed");
  }
  return data;
}

async function loadDashboard() {
  const stats = await requestJson("/api/dashboard");
  document.querySelector("#totalPnl").textContent = formatMoney(stats.total_pnl);
  document.querySelector("#winRate").textContent = `${stats.win_rate}%`;
  document.querySelector("#tradeCount").textContent = stats.trade_count;
  document.querySelector("#rMultiple").textContent = stats.r_multiple.toFixed(2);
}

async function loadTrades() {
  const trades = await requestJson("/api/trades");
  tradesBody.innerHTML = "";

  for (const trade of trades) {
    const row = document.createElement("tr");
    const pnlClass = trade.pnl >= 0 ? "gain" : "loss";
    row.innerHTML = `
      <td>${trade.symbol}</td>
      <td>${trade.side}</td>
      <td>${trade.setup_tag}</td>
      <td>${formatNumber(trade.qty)}</td>
      <td>${formatMoney(trade.entry_price)}</td>
      <td class="${pnlClass}">${formatMoney(trade.pnl)}</td>
    `;
    tradesBody.append(row);
  }

  if (!trades.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="6">No trades yet.</td>';
    tradesBody.append(row);
  }
}

async function refresh() {
  try {
    await requestJson("/api/health");
    statusEl.textContent = "Server online";
    await Promise.all([loadDashboard(), loadTrades()]);
  } catch (error) {
    statusEl.textContent = "Server offline";
    formMessage.textContent = error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "";
  const payload = Object.fromEntries(new FormData(form).entries());

  try {
    await requestJson("/api/trades", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    form.reset();
    formMessage.textContent = "Trade added.";
    await refresh();
  } catch (error) {
    formMessage.textContent = error.message;
  }
});

refreshButton.addEventListener("click", refresh);
refresh();
