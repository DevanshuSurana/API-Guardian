"""Example client intentionally using a fictional old payment API."""

from fictional_payments import Client

client = Client(api_key="replace-me")


def checkout(amount_dollars: float):
    # This old API is fictional; it is only a migration demo fixture.
    return client.create_charge(amount=amount_dollars, currency="USD")
