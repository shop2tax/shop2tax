"""Integration tests for the OMS router endpoints."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from app.models import OmsStore
from app.services.oms_provider import OmsOrder, OmsOrderItem
from app.services.providers.billbee import BillbeeProvider

from tests.conftest import AUTH_HEADERS, _create_example_transaction


def _example_oms_order(
    *,
    order_id: str = "1001",
    order_number: str = "ET-12345",
    total_cost: Decimal = Decimal("49.99"),
    created_at: datetime = datetime(2026, 1, 15, 10, 0, tzinfo=UTC),
    customer_name: str = "Max Mustermann",
) -> OmsOrder:
    """Build a fake OmsOrder for testing."""
    return OmsOrder(
        order_id=order_id,
        order_number=order_number,
        invoice_number=None,
        invoice_number_prefix=None,
        state=3,
        created_at=created_at,
        total_cost=total_cost,
        currency="EUR",
        customer_name=customer_name,
        customer_email="max@example.com",
        shop_id=100,
        shop_name="Etsy Store",
        platform="Etsy",
        items=[
            OmsOrderItem(
                product_title="Handmade Mug",
                quantity=2,
                total_price=total_cost,
                sku="MUG-001",
                tax_index=1,
                tax_amount=Decimal("0"),
            )
        ],
        tags=["paid"],
        paid_amount=total_cost,
        is_paid=True,
        paid_at=None,
        tax_rate_1=None,
        tax_rate_2=None,
    )


def _patch_fetch_orders_cached(orders, is_cached=False, expires=datetime(2026, 2, 1, tzinfo=UTC)):
    return patch.object(
        BillbeeProvider,
        "fetch_orders_cached",
        new_callable=AsyncMock,
        return_value=(orders, is_cached, expires),
    )


def _patch_fetch_order_by_id(order):
    return patch.object(BillbeeProvider, "fetch_order_by_id", new_callable=AsyncMock, return_value=order)


# --- Provider Endpoint ---


class TestListProviders:
    def should_return_seeded_billbee_provider(self, api_client, oms_provider_record):
        response = api_client.get("/api/v1/oms/providers", headers=AUTH_HEADERS)

        assert response.status_code == 200
        providers = response.json()
        assert len(providers) == 1
        assert providers[0]["display_name"] == "Billbee"
        assert providers[0]["type"] == "billbee"
        assert providers[0]["is_active"] is True


# --- Settings Endpoints ---


class TestGetSettings:
    def should_return_has_credentials_from_environment(self, api_client):
        """Credentials are read from environment variables (set in conftest.py)."""
        response = api_client.get("/api/v1/oms/settings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["has_credentials"] is True
        assert data["stores"] == []

    def should_include_stores_in_response(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="My Etsy Shop",
            external_shop_id=100,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.get("/api/v1/oms/settings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        stores = response.json()["stores"]
        assert len(stores) == 1
        assert stores[0]["store_type"] == "etsy"
        assert stores[0]["label"] == "My Etsy Shop"
        assert stores[0]["external_shop_id"] == 100

    def should_reject_unauthenticated_request(self, api_client):
        """Missing X-User-ID header defaults to empty → 401 Unauthorized."""
        response = api_client.get("/api/v1/oms/settings")

        assert response.status_code == 401

    def should_return_no_credentials_when_env_vars_missing(self, api_client):
        """When BILLBEE_USERNAME/PASSWORD not set, has_credentials is False."""
        from app.config import Settings

        empty_settings = Settings(
            database_url="postgresql://x:x@localhost/x",
            billbee_username="",
            billbee_password="",
        )
        with patch("app.config.get_settings", return_value=empty_settings):
            response = api_client.get("/api/v1/oms/settings", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json()["has_credentials"] is False


# --- Store Mapping Endpoints ---


class TestCreateStore:
    def should_create_store_mapping(self, api_client):
        response = api_client.post(
            "/api/v1/oms/stores",
            json={
                "store_type": "etsy",
                "label": "My Etsy Shop",
                "external_shop_id": 100,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["store_type"] == "etsy"
        assert data["label"] == "My Etsy Shop"
        assert data["external_shop_id"] == 100
        assert "id" in data
        assert "created_at" in data

    def should_create_store_with_explicit_provider_id(self, api_client, oms_provider_record):
        response = api_client.post(
            "/api/v1/oms/stores",
            json={
                "store_type": "amazon",
                "label": "Amazon Shop",
                "external_shop_id": 200,
                "provider_id": oms_provider_record.id,
            },
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 201
        assert response.json()["provider_id"] == oms_provider_record.id


class TestUpdateStore:
    def should_update_store_label(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="Old Label",
            external_shop_id=100,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.put(
            f"/api/v1/oms/stores/{store.id}",
            json={"label": "New Label"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["label"] == "New Label"
        assert response.json()["store_type"] == "etsy"  # unchanged

    def should_return_404_for_nonexistent_store(self, api_client):
        response = api_client.put(
            "/api/v1/oms/stores/nonexistent-id",
            json={"label": "New Label"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 404

    def should_update_any_store_in_shared_tenant(self, api_client, database_session):
        """Shared tenant: any user can update any store."""
        from app.models import User

        other_user = User(
            id="other-user-id",
            provider_id="google-other",
            provider_type="google",
            email="other@example.com",
            name="Other User",
        )
        database_session.add(other_user)
        database_session.flush()

        store = OmsStore(
            user_id="other-user-id",
            store_type="amazon",
            label="Other User Store",
            external_shop_id=200,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.put(
            f"/api/v1/oms/stores/{store.id}",
            json={"label": "Updated Label"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        assert response.json()["label"] == "Updated Label"


class TestDeleteStore:
    def should_delete_store(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="shopify",
            label="Shopify Store",
            external_shop_id=300,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.delete(f"/api/v1/oms/stores/{store.id}", headers=AUTH_HEADERS)

        assert response.status_code == 204

    def should_return_404_for_nonexistent_store(self, api_client):
        response = api_client.delete("/api/v1/oms/stores/nonexistent-id", headers=AUTH_HEADERS)

        assert response.status_code == 404


# --- Orders Endpoints ---


class TestListOrders:
    def should_return_orders_from_provider(self, api_client, oms_provider_record):
        fake_orders = [_example_oms_order()]

        with _patch_fetch_orders_cached(fake_orders):
            response = api_client.get("/api/v1/oms/orders", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["cached"] is False
        assert data["items"][0]["order_number"] == "ET-12345"

    def should_pass_store_ids_to_provider(self, api_client, database_session, oms_provider_record):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="Etsy",
            external_shop_id=42,
        )
        database_session.add(store)
        database_session.flush()

        with _patch_fetch_orders_cached([], is_cached=True) as mock_fetch:
            api_client.get("/api/v1/oms/orders", headers=AUTH_HEADERS)

            call_kwargs = mock_fetch.call_args.kwargs
            assert call_kwargs["store_ids"] == [42]


class TestGetOrder:
    def should_return_single_order(self, api_client, oms_provider_record):
        order = _example_oms_order(order_id="2001", order_number="ET-99999")

        with _patch_fetch_order_by_id(order) as mock_fetch:
            response = api_client.get("/api/v1/oms/orders/2001", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == "2001"
        assert data["order_number"] == "ET-99999"
        mock_fetch.assert_called_once()

    def should_return_404_when_order_not_found(self, api_client, oms_provider_record):
        with _patch_fetch_order_by_id(None):
            response = api_client.get("/api/v1/oms/orders/9999", headers=AUTH_HEADERS)

        assert response.status_code == 404
        assert response.json()["detail"] == "Order '9999' not found"


# --- Match Endpoint ---


class TestFindMatches:
    def should_return_404_for_nonexistent_transaction(self, api_client, oms_provider_record):
        with _patch_fetch_orders_cached([]):
            response = api_client.get("/api/v1/oms/match/nonexistent-id", headers=AUTH_HEADERS)

        assert response.status_code == 404

    def should_return_match_suggestions(self, api_client, database_session, oms_provider_record):
        transaction = _create_example_transaction(
            database_session,
            amount=Decimal("-49.99"),
            counterparty="Mustermann",
            transaction_date=datetime(2026, 1, 15).date(),
        )

        fake_orders = [_example_oms_order(total_cost=Decimal("49.99"))]

        with _patch_fetch_orders_cached(fake_orders, is_cached=True):
            response = api_client.get(f"/api/v1/oms/match/{transaction.id}", headers=AUTH_HEADERS)

        assert response.status_code == 200
        matches = response.json()
        assert len(matches) >= 1
        assert matches[0]["oms_order_id"] == "1001"
        assert matches[0]["confidence"] > 0


# --- Link / Unlink Endpoints ---


class TestLinkTransaction:
    def should_link_transaction_to_order(self, api_client, database_session, oms_provider_record):
        transaction = _create_example_transaction(database_session, amount=Decimal("-49.99"))
        order = _example_oms_order(total_cost=Decimal("49.99"))

        with _patch_fetch_order_by_id(order):
            response = api_client.post(
                f"/api/v1/oms/link/{transaction.id}",
                json={"oms_order_id": "1001"},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["oms_order_id"] == "1001"

    def should_track_partial_payment(self, api_client, database_session, oms_provider_record):
        transaction = _create_example_transaction(database_session, amount=Decimal("-30.00"))
        order = _example_oms_order(total_cost=Decimal("49.99"))

        with _patch_fetch_order_by_id(order):
            response = api_client.post(
                f"/api/v1/oms/link/{transaction.id}",
                json={"oms_order_id": "1001", "amount_covered": "30.00"},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 200
        data = response.json()
        assert Decimal(str(data["remaining_amount"])) == Decimal("19.99")

    def should_return_404_for_nonexistent_transaction(self, api_client, oms_provider_record):
        with _patch_fetch_order_by_id(None):
            response = api_client.post(
                "/api/v1/oms/link/nonexistent-id",
                json={"oms_order_id": "1001"},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 404

    def should_link_with_no_remaining_amount_when_order_not_found(self, api_client, database_session, oms_provider_record):
        """remaining_amount set to None when fetch_order_by_id returns None."""
        transaction = _create_example_transaction(database_session, amount=Decimal("-49.99"))

        with _patch_fetch_order_by_id(None):
            response = api_client.post(
                f"/api/v1/oms/link/{transaction.id}",
                json={"oms_order_id": "1001"},
                headers=AUTH_HEADERS,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["oms_order_id"] == "1001"
        assert data["remaining_amount"] is None


class TestUnlinkTransaction:
    def should_unlink_and_clear_oms_order(self, api_client, database_session):
        transaction = _create_example_transaction(database_session, amount=Decimal("-49.99"))
        transaction.oms_order_id = "1001"
        database_session.flush()

        response = api_client.delete(f"/api/v1/oms/link/{transaction.id}", headers=AUTH_HEADERS)

        assert response.status_code == 200
        data = response.json()
        assert data["oms_order_id"] is None

    def should_return_404_for_nonexistent_transaction(self, api_client):
        response = api_client.delete("/api/v1/oms/link/nonexistent-id", headers=AUTH_HEADERS)

        assert response.status_code == 404


# --- Cache Endpoint ---


class TestClearCache:
    def should_clear_cache(self, api_client):
        with patch("app.services.providers.billbee.clear_cache", return_value=2) as mock_clear:
            response = api_client.post("/api/v1/oms/cache/clear", headers=AUTH_HEADERS)

        assert response.status_code == 200
        assert response.json()["cleared_entries"] == 2
        mock_clear.assert_called_once_with()


# --- _get_db_user: user auto-creation ---


class TestGetDbUser:
    def should_auto_create_user_on_first_request(self, api_client, database_session):
        """deps.py auto-creates user in DB on first request, so _get_db_user always finds them."""
        new_user_headers = {
            "x-user-id": "brand-new-user-id",
            "x-user-name": "New User",
            "x-user-email": "new@example.com",
        }
        response = api_client.get("/api/v1/oms/settings", headers=new_user_headers)

        assert response.status_code == 200


# --- update_store: store_type and external_shop_id fields ---


class TestUpdateStoreFields:
    def should_update_store_type(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="My Store",
            external_shop_id=100,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.put(
            f"/api/v1/oms/stores/{store.id}",
            json={"store_type": "amazon"},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["store_type"] == "amazon"
        assert data["label"] == "My Store"  # unchanged
        assert data["external_shop_id"] == 100  # unchanged

    def should_update_external_shop_id(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="My Store",
            external_shop_id=100,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.put(
            f"/api/v1/oms/stores/{store.id}",
            json={"external_shop_id": 999},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["external_shop_id"] == 999
        assert data["store_type"] == "etsy"  # unchanged

    def should_update_all_fields_at_once(self, api_client, database_session):
        store = OmsStore(
            user_id="test-user-id",
            store_type="etsy",
            label="Old",
            external_shop_id=100,
        )
        database_session.add(store)
        database_session.flush()

        response = api_client.put(
            f"/api/v1/oms/stores/{store.id}",
            json={"store_type": "shopify", "label": "New", "external_shop_id": 777},
            headers=AUTH_HEADERS,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["store_type"] == "shopify"
        assert data["label"] == "New"
        assert data["external_shop_id"] == 777
