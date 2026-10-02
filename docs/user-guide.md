# Using Budgenta

[Back to README](../README.md)

## Telegram login and public accounts

1. Click **Log in with Telegram** on the login page.
2. Click **Open Telegram**, then **Start** in the bot if Telegram asks.
3. Compare the six-character code with your browser and press **Approve login**.
4. Return to the original browser and choose **Continue as …**.

The bot creates a user account automatically. Anyone with Telegram can register; there is no Telegram ID allowlist. Each user's accounts, transactions, debts, goals, and savings belong only to that user.

Login requests expire after five minutes, are bound to an HttpOnly browser cookie, and can be consumed once. The browser explicitly confirms the Telegram identity before creating a seven-day session. This bot-confirmation flow works on localhost without a Telegram widget domain. The legacy signed Telegram-widget API is still supported for clients integrating it.

Telegram sign-in is required in every environment, including localhost. For a public deployment, set `COOKIE_SECURE=true` and `APP_ORIGIN=https://your-domain.example` (no trailing slash), and run behind an HTTPS reverse proxy. Writes require the exact configured Origin, including API clients.

## Telegram menus

Send `/start` or `/home` in a private chat. Telegram is a focused companion:

- **Income / Expense**: choose an account and currency, amount, category, note, and date; review and confirm.
- **Transfer / Exchange** (`/transfer`, `/exchange`): choose source and destination wallets, amount, and date; exchanges accept your custom rate or the final amount received. Review both balance changes before confirming.
- **Current state** (`/report` or `/balance`): current estimate in your main currency using its own saved Current state filters, this month's income/expenses, outstanding debts, and goal progress.
- **Open website** (`/web`): open the configured website address for account, debt, goal, savings, and report-schedule management.

Scheduled daily, weekly, and monthly reports still arrive in the chat. **Current state** is the only on-demand report in the bot. Management forms have been removed from Telegram, including unfinished forms from older versions. **Back** revisits the previous transaction step; **Home** or **Cancel** discards the unfinished transaction. Transaction state and update receipts persist across restarts and remain encrypted. Telegram update redelivery cannot duplicate financial writes. A reply can appear twice if Telegram accepted it just before the worker stopped, but the transaction remains recorded once.

Run one bot worker. PostgreSQL enforces a worker lock. An active Telegram webhook prevents long polling; remove an old webhook before using this worker. The app does not silently remove existing webhooks. Telegram itself stores bot messages; database encryption does not make Telegram conversations end-to-end encrypted.

## Main currency and dashboard estimate

Open the gear button on the **Estimated balance** card, choose **Main currency**, and press **Save currency**. USD, **EUR**, ARS, **UAH**, USDT, TRX, BTC, and ETH are available. The same choice is also available under Reports and applies to your dashboard estimate and every Telegram report total. Each user has their own setting; USD is the default. Changing it does not exchange money or alter account balances.

UAH rates update automatically from the National Bank of Ukraine. Expand **Exchange rates & sources** to see the UAH quote and date even if you do not hold UAH, unless rate details or UAH are excluded. Rates are refreshed on demand after the five-minute cache expires. EUR uses Frankfurter reference rates.

## Budget behavior

- Cash, debit cards, and credit cards: USD/EUR/ARS/UAH. PayPal: USD/EUR/ARS. Crypto: USDT/TRX/BTC/ETH. Savings supports all eight currencies. Each account can hold multiple currencies, with a separate balance for each. Cash USD + ARS or Crypto USDT + TRX occupy one card. Choose initial currencies when creating a web account, or use **Add currency** on the website. **Merge** combines two accounts of the same type under the destination name; matching currency balances are added and transactions, debt links, savings rules, and report selections are preserved. Merging does not convert currencies or create income. Accounts cannot be automatically split again. Existing accounts remain separate until you choose to merge them.
- Fiat amounts have two fractional digits; USDT/TRX amounts allow six and BTC/ETH allow eight. Telegram reports display native account amounts with two decimal places without rounding stored balances; estimated totals use the precision of the chosen main currency. Backend arithmetic uses Decimal.
- Expense suggestions: **Grocery, Outside Food, Self Care, Rent, Health, Clothes, Emergency, Debts, Leisure, Delivery, Home, Transport, Subscriptions**. Custom categories remain available.
- Negative credit-card balances represent debt. Cash, debit cards, PayPal, and crypto cannot spend more than their current balance. Transfers require matching currencies and sufficient funds.
- Savings are separate accounts, available in all supported currencies. Deposits and withdrawals are paired transfers between matching currencies. They change the two balances without creating income or expenses. Historical monthly surplus (income minus expenses) remains in Reports; it is not money added to a savings account. Closing a month blocks new backdated entries, while corrections by deletion still recalculate its report.
- Debts track the original amount, amount repaid, due date, and note. Adding a debt does not create income. Repayments reduce the debt and atomically record a **Debts** expense from an account in the same currency. Avoid separately duplicating a card liability in the Debts list.
- Goals track a target, progress, and optional deadline. Attach one or more savings currency balances matching the goal currency; progress then follows their combined actual balance automatically, including deposits, withdrawals, corrections, and transaction reversals. Each savings currency balance can fund only one active goal. Links replace manual progress and do not add money to account totals. With no savings links, progress can be updated manually.
- Future-dated manual ledger entries, live bank integrations, recurring expense payments, and transaction editing are not included. Monthly savings transfers and deletion with reversal are supported.

## Manage accounts, debts, goals, and savings

All management controls are on the website. Open the small gear button on an account or savings card to access its actions:

- **Accounts / Savings:** edit the name and account type, add currencies, merge, correct a balance, archive, or restore. Unsupported currencies, negative balances, goal links, and savings rules are checked before account-type changes.
- **Correct balance:** writes an auditable adjustment for the difference from the current balance. It is excluded from income and expenses and can be reversed through Transactions.
- **Archive account:** requires all currency balances to be zero and goal links removed. Transaction history remains available and attached savings rules are paused. Archived accounts disappear from active selections and can be restored. Reversing a transaction that restores money to an archived account automatically restores that account too.
- **Debts:** edit details, archive/restore, or click **Pay debt** and select a matching-currency account and payment amount. The expense and debt reduction happen together. An edited debt cannot be less than the amount already paid; its currency cannot change while repayments exist. Archiving retains its liability/history but hides it from active lists. Reversing a repayment reopens an archived debt if money is owed again.
- **Goals:** edit details, attach/unlink savings, archive, and restore. Unlinking in the form keeps the displayed amount as editable manual progress. Archiving snapshots current progress and releases savings links without moving money. Restored goals start with that manual snapshot; relink savings to resume live tracking.
- **Savings rules:** edit schedule/amount/accounts, pause/resume, remove, or restore. Removal stops future transfers and retains previous runs. Restored rules stay paused until explicitly resumed.

Archiving is reversible and preserves financial history. It does not erase transactions or move money. Merging savings that fund different goals is blocked until the conflicting goal link is removed.

## Account layout and Current state

Under **Accounts → Page settings**, enable or hide the **Debit**, **Credit**, and **Savings** sections. Debit contains cash, debit cards, PayPal, and crypto wallets; Credit contains credit cards. Savings is always displayed last. Empty sections are omitted automatically. Up/down buttons set a saved account order within each section; newly added accounts follow existing accounts. This layout also applies to account cards on Overview. Hiding a section does not exclude its money from totals: dashboard and report filters control those independently.

Existing `card` accounts retain credit-card behavior. To classify an existing card as debit, use its gear menu → **Edit account → Debit card**. Negative credit balances must be cleared before switching to debit. Account order and visibility are saved per user in encrypted preferences, and account merges update saved selections and order.

Under **Reports → Current state**, choose which accounts, savings, exchange-rate details, debts, goals, and current-month income/expenses appear in Telegram. Preview the saved report on the website. These settings are independent of the dashboard and scheduled daily/weekly/monthly reports. Existing users initially inherit their previous dashboard account/savings filters for Current state, then can configure it separately.

Current state combines each account's currencies and orders accounts by their total estimated **USD value, highest first**. A hidden rate-details section does not disable conversion. Only the overall balance is converted to your main currency; individual accounts show their original currency balances with two decimal places. Accounts with an unavailable quote appear last; available portions still contribute to the explicitly partial overall total. Stale/missing-rate warnings remain visible even when rate details are hidden.

Under **Reports**, every tab (**Current state, Daily, Weekly, Monthly, Dashboard**) has its own **Excluded currencies** checkboxes. Excluded currencies are removed from that view’s balances, USD total, income/expenses, and category breakdowns. On the dashboard they also disappear from account cards and recent activity; Current state additionally filters debts and goals. Accounts with no included currencies are omitted from the dashboard and Current state. Exclusions do not delete wallets or transactions, and the Accounts and Transactions pages retain everything. Uncheck a currency to include it again. Existing Current state exclusions are preserved; other tabs start with no exclusions.

Each tab also has an independent **Show exchange-rate details** toggle. Hiding details leaves conversion active for USD totals and sorting. Missing/stale-rate warnings remain visible. The dashboard toggle controls its **Exchange rates & sources** section.

UAH valuation uses the [National Bank of Ukraine official USD/UAH rate](https://bank.gov.ua/en/markets/exchangerates), inverted to USD per UAH. BTC and ETH use [CoinGecko simple prices](https://docs.coingecko.com/reference/simple-price), alongside the existing crypto quotes. Missing/stale quotes follow the same partial-total and cache warnings as existing currencies.

## Delete a mistaken transaction

Use **Delete** on the website Transactions page and confirm. Deletion reverses the whole operation atomically:

- Income/expense: the account balance and reports are recalculated.
- Transfer or savings deposit/withdrawal: both ledger entries are removed together.
- Debt payment: its expense is removed and the debt's paid amount is reduced.

Repeat deletion requests do not repeat the reversal. If the received money has already been spent, deletion is blocked until the dependent spending/withdrawals are undone; non-card balances cannot become negative. Corrections may affect closed months. Already delivered Telegram reports are historical snapshots; view a fresh report for corrected totals.

Deleted entries retain an encrypted audit tombstone, disappear from the active ledger, and no longer affect balances or reports. Deleting a scheduled transfer does not execute that month's rule again or cancel future occurrences. Pause the rule to stop future transfers.

Migration links old transfer pairs and old repayments only where they can be identified safely. Ambiguous legacy links are marked for review and deletion is blocked instead of guessing which debt or account to modify.

## Monthly savings and expense reports

In **Savings → Monthly rules**, choose a spending account, a savings account in the same currency, and either a fixed amount or **all remaining balance**. For example, move 100 USD on day 10, or sweep an account's positive balance on the last day. The website offers the same controls.

- Numbered days execute at **09:00**. Days 29–31 clamp to the last calendar day in short months.
- **Last day** executes at **23:59**. Manual “all remaining” deposits/withdrawals are also available immediately.
- Timezone: `APP_TIMEZONE`, default **America/Argentina/Buenos_Aires**. The worker checks approximately every 25 seconds while it is running.
- A new rule scheduled for today after its execution time runs on the next check. A day earlier than today starts next month.
- Insufficient funds skip a fixed deposit without partially transferring money. The result is stored and sent through Telegram.
- Rules execute in creation order. Edit, pause/resume, and removal/restoration are available on the website. Editing a rule does not repeat an occurrence already executed that month. Resuming skips intentionally paused past dates.
- Run records prevent duplicate transfers after restarts. Missed runs from older months are marked skipped, not charged as a backlog. A missed month-end sweep can catch up on the following day. Current-month missed runs execute when the worker resumes, using the actual execution date.

Under **Reports**, configure **daily, weekly, and monthly** Telegram delivery independently. Daily balance reports default to **09:15**, monthly reports to the **1st at 09:00**, and weekly reports start disabled (Monday at 09:15). Choose a delivery time, weekly weekday, monthly day, and IANA timezone. Reports contain the current estimated balance in your main currency and expenses for yesterday, the previous seven days, or the previous calendar month, respectively. The balance is a current snapshot at delivery; the expense period is shown separately.

Each report has its own account selection, currency exclusions, rate-details toggle, savings inclusion switch, and expense-category switch. Account selection includes currencies of that account except those explicitly excluded on the report tab. **All accounts** automatically includes future accounts; selecting no accounts gives an empty report. Savings transfers never count as expenses. The dashboard has separate account, currency, and savings filters, applied consistently to balances, account cards, monthly totals, and recent activity. `/balance` uses the independent Current state settings. The full Accounts and Transactions pages remain available for managing all records. Preview a saved report on the website; use **Current state** for an on-demand summary in Telegram. Configure report settings on the website.

The report timezone defaults to `APP_TIMEZONE` and follows daylight saving changes. Monthly report days 29–31 clamp to the final day of shorter months. A report is queued once per local daily/weekly/monthly occurrence; changing its delivery time after it was queued does not send it again. Daily and weekly reports can catch up later on their scheduled day; missed earlier days are skipped. Monthly reports can catch up later in the same month. Keep the Telegram worker running for these automations; stopping your computer stops the local scheduler. Savings transfer rules continue to use `APP_TIMEZONE` independently of report preferences.

Scheduled transfers and report outbox records are durable. A notification can repeat if Telegram accepted it immediately before a worker crash, but the financial transfer is not repeated.

## Category percentages and form lists

Category percentages use **total expenses across all included currencies**, converted to USD at the current report exchange rates, after the report’s account, currency, savings, and date filters. Spending in the same category across currencies is combined into one share, with the original amounts shown beside it. For example, 10 USD of Grocery plus 1,000 ARS of Grocery valued at 1 USD, and 5 EUR of Rent valued at 10 USD, produces Grocery 52.38% and Rent 47.62% of the 21 USD total. Income, opening balances, corrections, transfers, and exchanges are not expenses. Categories are sorted by their combined USD value. Shares use unrounded conversions and are displayed to two decimal places, so their rounded sum may differ slightly from 100%. These are estimates using current rates, not historical rates on each transaction date. If any included expense currency is missing a rate, percentages are withheld while original amounts remain visible; cached rates display a warning. Hiding rate details does not disable conversion.

The website’s monthly expense report and Telegram daily/weekly/monthly reports show these shares when **Include expenses by category** is enabled. Current state has the same switch under its current-month summary. Disabling the category breakdown hides the shares too.

Dropdowns open their complete scrollable option list on focus or click; typing filters the options. The current selection is shown as a placeholder, so typing starts a new search immediately. Use arrows and Enter to choose, Escape to dismiss, or click an option. Category and timezone fields also accept custom text. A new transaction starts with an empty category and a hint instead of prefilled Grocery. New opening balances and manually entered goal savings use a zero placeholder and default to zero if left empty.


## Transfers and currency exchanges

Use **Transfer between accounts** or **Exchange currencies** on Accounts, or the **Transfer / Exchange** buttons on Transactions. Telegram has **↔ Transfer** and **⇄ Exchange** buttons and `/transfer` and `/exchange` commands. Both offer a review before confirmation, with Back/Home/Cancel in the bot.

- **Transfer:** move the same currency between two wallets, including deposits into or withdrawals from savings.
- **Exchange:** move money between different currencies, within one multi-currency account or across account types. For example, exchange USDT in a crypto wallet for ARS in Cash, or EUR in a card account for USD in savings. Add the destination currency to the account first if needed.
- Choose **Enter rate** to use the actual **custom exchange rate**, always as **destination units per 1 source unit**. Sending 10 USDT at 1,500 ARS per USDT subtracts 10 USDT and adds 15,000 ARS. For the reverse direction, enter the reciprocal rate. Dashboard market estimates do not set the recorded rate.
- Alternatively, choose **Enter amount received** on the website or **Enter received amount** in Telegram. Enter the final amount in the destination currency; the review calculates the rate as received ÷ sent. The exact received amount is recorded, even when the calculated rate is a repeating decimal. A rounded calculated rate is marked ≈ and displayed to 18 significant digits. The amount must already fit the destination currency precision.
- The review shows the exact received amount. When entering a rate, calculation uses decimal arithmetic and rounds half up: fiat to 2 places, USDT/TRX to 6, BTC/ETH to 8. Amounts that round to zero are rejected. Manually entered rates support up to 18 decimal places. This records your exchange; it does not execute a trade or move funds at an external provider. Record any separate fee as an expense.
- Both entries share one operation. Deleting either entry on Transactions reverses both, including linked savings goal progress. If received money has already been spent, undo dependent spending first. Transfers and exchanges do not count toward income, expenses, or expense-category percentages.
- Source funds must be available, both wallets must be active and yours, and the date must be in an open period and not in the future. Confirmation rechecks these conditions. Excluding a currency from reports does not prevent using it in a transfer or exchange.


## Custom income and expense purposes

In **Add transaction → Category**, pick an existing category or type your own purpose, such as **Watches** for an expense or **Money from parents** for income. Select **Save category for future use** to keep it in your category list. Leave it unchecked for a one-time purpose. The choice is saved when the transaction succeeds; cancelling or a failed transaction does not save a category.

Saved categories are private to your user, encrypted in the database, and separate for income and expenses. They appear in website dropdowns and Telegram category buttons. Refresh an already-open website to load categories saved from another device. In Telegram, type a new category and choose **Save category** or **Use once**, then finish and confirm the transaction. Back, Home, and Cancel remain available.

Duplicate names differing only in capitalization or whitespace reuse the existing saved category. Deleting a transaction keeps its saved category available for future use. Previously entered one-time categories are not automatically added to the saved list; type the name again and select the save option on a new transaction.


## Fill an amount with All

Use **All** beside an expense, transfer, exchange's amount to send, savings deposit/withdrawal, or debt repayment amount. It copies the selected source wallet's positive balance in that currency, including full crypto precision. Debt repayments are capped at the remaining debt. The button is disabled if the selected balance is zero or negative. In Telegram, choose **All** at the amount step for expenses, transfers, or exchanges.

This fills the amount for review; it does not submit the transaction. You can change the amount manually. Changing the source account clears an amount filled with All on the website. Balances are validated again when the transaction is saved. Income, exchange rates, and final received amounts have no All button because they are not spending an existing source balance. For recurring savings sweeps, continue to choose **All remaining balance** as the rule mode.


## Transfer statistics

Current state, daily/weekly/monthly reports, and the dashboard show **Transferred out** and **Received from transfers** per currency. These include ordinary transfers, currency exchanges, and savings deposits/withdrawals. For example, exchanging 100 USDT for 150,000 ARS shows 100 USDT transferred out and 150,000 ARS received from transfers. It creates no income or expense.

Each selected account's transaction leg is counted once. A transfer between two included accounts in the same currency appears in both outgoing and incoming totals; these are movement totals, not net spending. Account, savings, currency, and date filters apply to each leg independently. Deleting a transfer/exchange removes both legs from these statistics. Income less expenses (the existing surplus measure) continues to exclude transfers.

Zero figures and empty currency rows are hidden. A positive Telegram amount that would round to zero is shown as **<0.01**, preserving visibility of small crypto movements. Opening balances and balance corrections are not income, expenses, or transfers.
