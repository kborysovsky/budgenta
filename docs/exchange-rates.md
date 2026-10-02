# Exchange rates

[Back to README](../README.md)

Choose **Main currency** using the gear button on the dashboard's estimated-balance card, or under **Reports**. USD is the default; EUR, ARS, UAH, USDT, TRX, BTC, and ETH are also supported. This encrypted, per-user setting applies to the dashboard estimate and Telegram Current state, daily, weekly, and monthly totals. Account and transaction amounts stay in their original currencies. USD remains the common unit for account ordering and expense-share calculations.

Cross-currency estimates use `amount × source USD price / main-currency USD price`, without rounding the intermediate USD value. Fiat totals have two decimal places; crypto totals retain six (USDT/TRX) or eight (BTC/ETH). A missing main-currency rate makes a total requiring conversion unavailable, rather than showing a zero or relabeling USD. Missing source rates produce an explicitly partial total. Same-currency balances can be totaled without a conversion rate.

- ARS: [DolarApi blue-dollar **venta**](https://dolarapi.com/docs/argentina/operations/get-dolar-blue). `USD = ARS / venta`, representing buying USD with pesos.
- EUR: [Frankfurter EUR/USD reference rate](https://frankfurter.dev/v1/). `USD = EUR × rate`.
- UAH: [National Bank of Ukraine official USD/UAH rate](https://bank.gov.ua/en/markets/exchangerates). `USD = UAH / official USD rate`.
- USDT, TRX, BTC, and ETH: [CoinGecko USD prices](https://docs.coingecko.com/reference/simple-price), without assuming a fixed USDT peg. `COINGECKO_API_KEY` is optional for a Demo API key; provider limits may require it.

The dashboard's **Exchange rates & sources** list includes the current UAH reference rate even without a UAH wallet, unless UAH is excluded or rate details are hidden. Its source and publication date are displayed. A missing reference quote does not affect a total that does not need it. Selecting UAH as the main currency fetches its rate for conversion even without a UAH account; EUR works the same way.

ARS, EUR, UAH, USDT, BTC, and ETH rates are cached for five minutes. TRX has a shared database quote: the worker obtains an initial quote and refreshes at/after **10:00 in each configured report timezone**, once per local day. Web and Telegram valuations read that same quote, including its source timestamp. Failed scheduled refreshes retry after five minutes while the worker runs. TRX quotes older than 26 hours are labeled cached, and are discarded after three days; an on-demand fetch is used if no usable stored quote exists. Weekends and holidays can use the latest published fiat quote. Implausibly old quotes are rejected. A provider outage may use a cached quote for up to 24 hours, explicitly marked as cached. If no usable quote exists, the currency is excluded and the total is labeled **partial**. Rate requests never include your account names, balances, or identity. These are estimates, not executable exchange quotes. Debt records are shown separately and are not deducted from account balances, preventing automatic double counting of card liabilities.
