# Plaid API Integration (Agent 2)

## Next Steps for Plaid Integration

1. Install the `plaid-python` package in your environment:
   ```sh
   pip install plaid-python
   ```
2. Add the following environment variables to your project (e.g., in a `.env` file or your deployment environment):
   - `PLAID_CLIENT_ID`
   - `PLAID_SECRET`
   - `PLAID_ENV` (sandbox, development, or production)
   - `PLAID_PRODUCTS` (e.g., transactions, investments)
   - `PLAID_REDIRECT_URI` (if using OAuth)
3. Backend logic:
   - Implement Plaid Link token creation and exchange endpoints in `views.py`.
   - Store access tokens securely (never expose to frontend).
   - Use Plaid API to fetch accounts and transactions, and save them to the `Account` and `Transaction` models.
4. Frontend logic:
   - Wire up the Plaid Link button in `connect_plaid.html` to call the backend for a link token, then launch Plaid Link.

See the official Plaid docs: https://plaid.com/docs/api/

---

**Manual entry and CSV upload are scaffolded and ready for implementation.**
