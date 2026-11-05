"""
Tests for restocking order API endpoints.
"""
import pytest

from mock_data import restocking_orders


@pytest.fixture(autouse=True)
def clear_restocking_orders():
    """POST appends to in-memory state, so reset it around every test."""
    restocking_orders.clear()
    yield
    restocking_orders.clear()


def _get_item(client, sku):
    items = client.get("/api/inventory").json()
    return next(item for item in items if item["sku"] == sku)


class TestRestockingOrderEndpoints:
    """Test suite for restocking order endpoints."""

    def test_get_restocking_orders_empty(self, client):
        """Test that no orders exist before any are submitted."""
        response = client.get("/api/restocking-orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_restocking_order(self, client):
        """Test submitting a valid order."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "WDG-001", "quantity": 10}]}
        )
        assert response.status_code == 201

        order = response.json()
        assert order["status"] == "Submitted"
        assert order["id"].startswith("RST-")
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == "WDG-001"
        assert order["items"][0]["quantity"] == 10

    def test_restocking_order_cost_from_inventory(self, client):
        """Test that costs come from inventory, not the client."""
        item = _get_item(client, "WDG-001")
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "WDG-001", "quantity": 10}]}
        )
        order = response.json()

        assert abs(order["items"][0]["unit_cost"] - item["unit_cost"]) < 0.01
        assert abs(order["total_cost"] - 10 * item["unit_cost"]) < 0.01

    def test_restocking_order_lead_time_is_longest_item(self, client):
        """Test that order lead time is the maximum across items."""
        fast = _get_item(client, "FLT-405")
        slow = _get_item(client, "CTL-330")
        response = client.post(
            "/api/restocking-orders",
            json={"items": [
                {"sku": "FLT-405", "quantity": 5},
                {"sku": "CTL-330", "quantity": 5}
            ]}
        )
        order = response.json()

        assert fast["lead_time_days"] < slow["lead_time_days"]
        assert order["lead_time_days"] == slow["lead_time_days"]
        assert "-" in order["expected_delivery"]
        assert order["expected_delivery"] > order["created_date"]

    def test_get_restocking_orders_lists_created_order(self, client):
        """Test that a submitted order shows up in the list, newest first."""
        first = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "WDG-001", "quantity": 1}]}
        ).json()
        second = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "GSK-203", "quantity": 1}]}
        ).json()

        data = client.get("/api/restocking-orders").json()
        assert [o["id"] for o in data] == [second["id"], first["id"]]

    def test_create_restocking_order_empty_items(self, client):
        """Test that an order with no items is rejected."""
        response = client.post("/api/restocking-orders", json={"items": []})
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_create_restocking_order_unknown_sku(self, client):
        """Test that an unknown SKU is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "NOPE-999", "quantity": 1}]}
        )
        assert response.status_code == 400
        assert "unknown sku" in response.json()["detail"].lower()

    def test_create_restocking_order_invalid_quantity(self, client):
        """Test that a non-positive quantity is rejected."""
        response = client.post(
            "/api/restocking-orders",
            json={"items": [{"sku": "WDG-001", "quantity": 0}]}
        )
        assert response.status_code == 400

    def test_rejected_order_is_not_stored(self, client):
        """Test that a failed submission leaves no order behind."""
        client.post("/api/restocking-orders", json={"items": []})
        assert client.get("/api/restocking-orders").json() == []
