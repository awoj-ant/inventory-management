"""
Tests for reports endpoints and restocking order creation.

Covers critical backend logic with zero prior test coverage:
- Quarter filter expansion (QUARTER_MAP)
- Quarterly revenue aggregation and avg_order_value calculation
- Restocking order validation and total_value calculation
"""
import pytest


class TestReportsEndpoints:
    """Test suite for reports-related endpoints and the quarter filter they depend on."""

    def test_orders_quarter_filter_expansion(self, client):
        """Test that month=Q1-2025 expands to Jan/Feb/Mar 2025 via QUARTER_MAP."""
        response = client.get("/api/orders?month=Q1-2025")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

        # Every returned order must have a date in Q1 2025
        valid_months = {"2025-01", "2025-02", "2025-03"}
        for order in data:
            assert "order_date" in order
            # order_date is ISO format; first 7 chars give YYYY-MM
            assert order["order_date"][:7] in valid_months

    def test_quarterly_report_revenue_matches_orders(self, client):
        """Test that quarterly total_revenue matches sum of order total_values."""
        # Get quarterly report
        reports_response = client.get("/api/reports/quarterly")
        assert reports_response.status_code == 200

        reports = reports_response.json()
        assert isinstance(reports, list)
        assert len(reports) > 0

        # Find Q1-2025 entry
        q1 = next((q for q in reports if q["quarter"] == "Q1-2025"), None)
        assert q1 is not None, "Q1-2025 missing from quarterly report"

        # Cross-validate against raw orders filtered by the same quarter
        orders_response = client.get("/api/orders?month=Q1-2025")
        q1_orders = orders_response.json()

        expected_revenue = sum(order["total_value"] for order in q1_orders)
        expected_count = len(q1_orders)

        # Revenue aggregation must match (allow float tolerance)
        assert abs(q1["total_revenue"] - expected_revenue) < 0.01
        assert q1["total_orders"] == expected_count

    def test_quarterly_report_avg_order_value_calculation(self, client):
        """Test that avg_order_value equals total_revenue / total_orders."""
        response = client.get("/api/reports/quarterly")
        assert response.status_code == 200

        reports = response.json()
        assert len(reports) > 0

        for quarter in reports:
            assert "total_revenue" in quarter
            assert "total_orders" in quarter
            assert "avg_order_value" in quarter
            assert "fulfillment_rate" in quarter

            # Backend only computes avg when total_orders > 0, so this is safe
            assert quarter["total_orders"] > 0

            expected_avg = round(quarter["total_revenue"] / quarter["total_orders"], 2)
            assert abs(quarter["avg_order_value"] - expected_avg) < 0.01

            # Fulfillment rate: delivered / total * 100, rounded to 1 decimal
            expected_rate = round(
                (quarter["delivered_orders"] / quarter["total_orders"]) * 100, 1
            )
            assert abs(quarter["fulfillment_rate"] - expected_rate) < 0.1


class TestRestockingOrderEndpoints:
    """Test suite for restocking order creation endpoint."""

    def test_create_restocking_order_invalid_lead_time(self, client):
        """Test that lead_time_days < 1 is rejected with 400."""
        payload = {
            "lead_time_days": 0,
            "items": [
                {
                    "sku": "PCB-001",
                    "name": "Single Layer PCB Assembly",
                    "quantity": 50,
                    "unit_cost": 24.99,
                }
            ],
        }
        response = client.post("/api/restocking-orders", json=payload)

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "lead_time_days" in data["detail"].lower()

    def test_create_restocking_order_total_value_calculation(self, client):
        """Test that total_value correctly sums quantity * unit_cost across items."""
        payload = {
            "lead_time_days": 7,
            "items": [
                {
                    "sku": "PCB-001",
                    "name": "Single Layer PCB Assembly",
                    "quantity": 10,
                    "unit_cost": 5.50,
                },
                {
                    "sku": "SNS-042",
                    "name": "Temperature Sensor",
                    "quantity": 3,
                    "unit_cost": 12.00,
                },
            ],
        }
        response = client.post("/api/restocking-orders", json=payload)

        assert response.status_code == 200
        order = response.json()

        # 10 * 5.50 + 3 * 12.00 = 55.00 + 36.00 = 91.00
        assert abs(order["total_value"] - 91.00) < 0.01

        # Verify order metadata set correctly by the endpoint
        assert order["status"] == "Processing"
        assert order["order_number"].startswith("RST-")
        assert order["order_type"] == "restocking"
        assert order["lead_time_days"] == 7
        assert len(order["items"]) == 2
