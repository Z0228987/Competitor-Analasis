/* Capital Market UI upgrade for the current dashboard */
(function(){
  const originalRenderMarket = window.renderMarket;
  if (typeof originalRenderMarket !== 'function') {
    console.error('renderMarket() was not found. Load this script after the dashboard script.');
    return;
  }

  const n = v => {
    const x = Number(String(v ?? '').replaceAll(',', ''));
    return Number.isFinite(x) ? x : null;
  };
  const canonName = c => String(c).toUpperCase() === 'AUMOVIO' ? 'Aumovio' : String(c);
  const cny = v => Number.isFinite(v) ? `${v.toFixed(2)} CNY` : 'N/A';
  const pct2 = v => Number.isFinite(v) ? `${(v * 100).toFixed(2)}%` : 'N/A';

  function rate(){
    const v = Number(localStorage.getItem('eurCnyRate'));
    return Number.isFinite(v) && v > 0 ? v : 8.35;
  }

  function companyHistory(company){
    return (window.marketHistory || [])
      .filter(r => canonName(r.company) === company && Number.isFinite(n(r.price)))
      .sort((a,b) => String(a.date).localeCompare(String(b.date)));
  }

  function dailyMove(company){
    const rows = companyHistory(company);
    if(rows.length < 2) return null;
    const latest = n(rows[rows.length - 1].price);
    const previous = n(rows[rows.length - 2].price);
    return latest !== null && previous ? latest / previous - 1 : null;
  }

  function convertedPrice(row){
    const price = n(row?.price);
    if(!Number.isFinite(price)) return null;
    return String(row.currency).toUpperCase() === 'EUR' ? price * rate() : price;
  }

  function latestRows(){
    const by = {};
    (window.market || []).forEach(row => {
      const company = canonName(row.company);
      if(!by[company] || String(row.date) > String(by[company].date)) by[company] = {...row, company};
    });
    return Object.values(by);
  }

  function ensureUpdateLabel(){
    let label = document.getElementById('marketLastUpdated');
    if(label) return label;
    label = document.createElement('div');
    label.id = 'marketLastUpdated';
    label.style.cssText = 'margin:-4px 0 13px;padding:9px 12px;border:1px solid rgba(255,255,255,.08);border-radius:11px;background:rgba(255,255,255,.035);color:#8e97af;font-size:9px;';
    const note = document.querySelector('#capital-market .market-note-dark');
    note?.insertAdjacentElement('afterend', label);
    return label;
  }

  async function updateTimestamp(){
    const label = ensureUpdateLabel();
    const latestDate = [...new Set((window.market || []).map(r => String(r.date || '')).filter(Boolean))].sort().at(-1);
    try{
      const response = await fetch((window.PATH && PATH.market) || 'data/market_data_verified.csv', {method:'HEAD', cache:'no-store'});
      const modified = response.headers.get('last-modified');
      if(modified){
        const text = new Intl.DateTimeFormat('zh-CN', {
          timeZone:'Asia/Shanghai', year:'numeric', month:'2-digit', day:'2-digit',
          hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false
        }).format(new Date(modified));
        label.textContent = `Latest market data update: ${text} (Shanghai time) · Latest trading-date snapshot: ${latestDate || 'N/A'}`;
        return;
      }
    }catch(e){ console.warn('Last-Modified header unavailable', e); }
    label.textContent = `Latest market data date: ${latestDate || 'N/A'} · Exact update time is unavailable from the current CSV fields.`;
  }

  function updateSelectedPrice(){
    const selected = document.getElementById('company')?.value;
    const row = latestRows().find(r => r.company === selected);
    const target = document.getElementById('sharePrice');
    if(!row || !target) return;
    const original = n(row.price);
    if(!Number.isFinite(original)){ target.textContent = 'N/A'; return; }
    if(String(row.currency).toUpperCase() === 'EUR'){
      target.innerHTML = `${original.toFixed(2)} EUR<br><small style="font-size:9px;color:#9ca4bb">≈ ${cny(convertedPrice(row))}</small>`;
    }else{
      target.textContent = `${original.toFixed(2)} ${row.currency || 'CNY'}`;
    }
  }

  function updatePeerPriceCells(){
    const rows = latestRows().sort((a,b) => n(b.market_cap) - n(a.market_cap));
    const trs = [...document.querySelectorAll('#marketPeerRows tr')];
    trs.forEach((tr,index) => {
      const row = rows[index];
      const cell = tr.children[1];
      if(!row || !cell || String(row.currency).toUpperCase() !== 'EUR') return;
      const original = n(row.price);
      const converted = convertedPrice(row);
      if(Number.isFinite(original) && Number.isFinite(converted)){
        cell.innerHTML = `${original.toFixed(2)} EUR<br><small>≈ ${converted.toFixed(2)} CNY</small>`;
      }
    });
  }

  function updateTicker(){
    const rows = latestRows().filter(r => Number.isFinite(n(r.price)));
    const loop = [...rows, ...rows];
    const ticker = document.getElementById('marketTicker');
    if(!ticker) return;
    ticker.innerHTML = loop.map(row => {
      const move = dailyMove(row.company);
      const down = Number.isFinite(move) && move < 0;
      const cls = down ? 'market-down' : 'market-up';
      const arrow = Number.isFinite(move) ? (down ? '▼' : '▲') : '';
      const original = `${n(row.price).toFixed(2)} ${row.currency || ''}`;
      const converted = String(row.currency).toUpperCase() === 'EUR' ? ` · ≈ ${convertedPrice(row).toFixed(2)} CNY` : '';
      return `<div class="market-tick"><b>${row.company === 'Aumovio' ? 'AUMOVIO' : row.company}</b><span>${original}${converted}</span><span class="${cls}">${Number.isFinite(move) ? `${arrow} ${Math.abs(move*100).toFixed(2)}% vs prior close` : 'N/A vs prior close'}</span></div>`;
    }).join('');
  }

  function enhance(){
    updateSelectedPrice();
    updatePeerPriceCells();
    updateTicker();
    updateTimestamp();
  }

  window.renderMarket = function(sel){
    originalRenderMarket(sel);
    enhance();
  };

  document.addEventListener('click', e => {
    if(e.target && e.target.id === 'applyFx') setTimeout(enhance, 0);
  });

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enhance);
  else enhance();
})();
