Place market_ui_upgrade.js next to index.html.
In index.html, add this line immediately before </body> and after the existing dashboard <script> block:
<script src="market_ui_upgrade.js"></script>

Changes:
1. AUMOVIO share price shows EUR original plus CNY equivalent using the EUR/CNY field.
2. The scrolling ticker shows latest close versus previous valid close, not YTD return.
3. Adds latest market-data update text using the CSV Last-Modified HTTP header, with latest trading-date fallback.
