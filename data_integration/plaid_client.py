"""
Thin wrapper around the Plaid SDK.

Imports happen lazily so the project keeps working without `plaid-python`
installed. Real network calls require PLAID_CLIENT_ID and PLAID_SECRET in env.
"""
from __future__ import annotations

import os
from typing import Iterable


class PlaidNotConfigured(RuntimeError):
    """Raised when Plaid is called but credentials/SDK aren't available."""


def is_configured() -> bool:
    return bool(os.environ.get('PLAID_CLIENT_ID') and os.environ.get('PLAID_SECRET'))


def _client():
    if not is_configured():
        raise PlaidNotConfigured(
            'Set PLAID_CLIENT_ID and PLAID_SECRET in your environment to use Plaid.'
        )
    try:
        from plaid.api import plaid_api
        from plaid.configuration import Configuration
        from plaid.api_client import ApiClient
    except ImportError as exc:
        raise PlaidNotConfigured(
            'plaid-python is not installed. Run `pip install plaid-python` to enable Plaid.'
        ) from exc

    host_lookup = {
        'sandbox': 'https://sandbox.plaid.com',
        'development': 'https://development.plaid.com',
        'production': 'https://production.plaid.com',
    }
    env = os.environ.get('PLAID_ENV', 'sandbox').lower()
    cfg = Configuration(
        host=host_lookup.get(env, host_lookup['sandbox']),
        api_key={
            'clientId': os.environ['PLAID_CLIENT_ID'],
            'secret': os.environ['PLAID_SECRET'],
        },
    )
    return plaid_api.PlaidApi(ApiClient(cfg))


def _products() -> Iterable[str]:
    raw = os.environ.get('PLAID_PRODUCTS', 'transactions')
    return [p.strip() for p in raw.split(',') if p.strip()]


def create_link_token(user) -> str:
    """Return a short-lived link_token for the browser SDK."""
    client = _client()

    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.products import Products
    from plaid.model.country_code import CountryCode

    request = LinkTokenCreateRequest(
        products=[Products(p) for p in _products()],
        client_name='Ridge & River Financial',
        country_codes=[CountryCode('US')],
        language='en',
        user=LinkTokenCreateRequestUser(client_user_id=str(user.pk)),
    )
    return client.link_token_create(request).link_token


def exchange_public_token(public_token: str) -> dict:
    """Exchange a public_token from the browser for an access_token + item_id."""
    client = _client()

    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest

    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    return {'access_token': resp.access_token, 'item_id': resp.item_id}


def fetch_accounts(access_token: str) -> list[dict]:
    client = _client()

    from plaid.model.accounts_get_request import AccountsGetRequest

    resp = client.accounts_get(AccountsGetRequest(access_token=access_token))
    return [
        {
            'account_id': a.account_id,
            'name': a.name,
            'official_name': a.official_name,
            'type': str(a.type),
            'subtype': str(a.subtype) if a.subtype else '',
            'mask': a.mask,
        }
        for a in resp.accounts
    ]


def get_institution_name(access_token: str) -> str:
    client = _client()

    from plaid.model.item_get_request import ItemGetRequest
    from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
    from plaid.model.country_code import CountryCode

    item_resp = client.item_get(ItemGetRequest(access_token=access_token))
    inst_id = item_resp.item.institution_id
    if not inst_id:
        return ''
    inst_resp = client.institutions_get_by_id(
        InstitutionsGetByIdRequest(institution_id=inst_id, country_codes=[CountryCode('US')])
    )
    return inst_resp.institution.name
