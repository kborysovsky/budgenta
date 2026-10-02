# Exchange rates

[Back to README](../README.md)

- ARS: [DolarApi blue-dollar **venta**](https://dolarapi.com/docs/argentina/operations/get-dolar-blue). `USD = ARS / venta`, representing buying USD with pesos.
- EUR: [Frankfurter EUR/USD reference rate](https://frankfurter.dev/v1/). `USD = EUR × rate`.
- UAH: [National Bank of Ukraine official USD/UAH rate](https://bank.gov.ua/en/markets/exchangerates). `USD = UAH / official USD rate`.
- USDT, TRX, BTC, and ETH: [CoinGecko USD prices](https://docs.coingecko.com/reference/simple-price), without assuming a fixed USDT peg. `COINGECKO_API_KEY` is optional for a Demo API key; provider limits may require it.

ARS, EUR, UAH, USDT, BTC, and ETH rates are cached for five minutes. TRX has a shared database quote: the worker obtains an initial quote and refreshes at/after **10:00 in each configured report timezone**, once per local day. Web and Telegram valuations read that same quote, including its source timestamp. Failed scheduled refreshes retry after five minutes while the worker runs. TRX quotes older than 26 hours are labeled cached, and are discarded after three days; an on-demand fetch is used if no usable stored quote exists. Weekends and holidays can use the latest published fiat quote. Implausibly old quotes are rejected. A provider outage may use a cached quote for up to 24 hours, explicitly marked as cached. If no usable quote exists, the currency is excluded and the total is labeled **partial**. Rate requests never include your account names, balances, or identity. These are estimates, not executable exchange quotes. Debt records are shown separately and are not deducted from account balances, preventing automatic double counting of card liabilities.
