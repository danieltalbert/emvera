# data_integration/README.md

# Data Integration App

This app integrates user financial data from APIs (Plaid), manual entry, and CSV upload.

## Models
- **Account**: User's financial accounts (checking, savings, credit, investment, debt)
- **Transaction**: Transactions linked to accounts
- **Investment**: Investment holdings
- **Debt**: Debt accounts and balances

## API Integration
- Uses Plaid API (https://plaid.com/docs/). You must set the following environment variables:
  - `PLAID_CLIENT_ID`
  - `PLAID_SECRET`
  - `PLAID_ENV` (sandbox, development, or production)
  - `PLAID_PRODUCTS` (e.g., transactions, investments)
  - `PLAID_REDIRECT_URI` (if using OAuth)

## Manual Entry
- Users can add accounts and transactions by hand via forms

## CSV Upload
- Users can upload CSV files to bulk-import transactions

## Setup
- Add `data_integration` to `INSTALLED_APPS` in your Django settings
- Run migrations

## Extensibility
- Models are designed for use by other apps (debt management, investment tracking, etc.)

