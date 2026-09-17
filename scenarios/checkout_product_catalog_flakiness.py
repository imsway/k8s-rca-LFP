"""Exploratory scenario: checkout's gRPC connection to product-catalog degrades.
Not scored -- ground truth is not fully understood (upstream image bug)."""
from scenarios.base import BaseScenario, kubectl


class CheckoutProductCatalogFlakinessScenario(BaseScenario):
    name = "checkout_product_catalog_flakiness"
    description = (
        "Exploratory/bonus scenario: checkout's gRPC connection to product-catalog degrades "
        "(sockets stuck CLOSE_WAIT / 'use of closed network connection'), causing checkout requests "
        "to either hang ~15s then 504, or fail fast with a generic 500 -- independent of any feature flag."
    )

    root_cause_service = "checkout"
    root_cause_type = "network"
    ground_truth_summary = (
        "checkout's gRPC client connections to product-catalog are in a broken state (CLOSE_WAIT / "
        "connection-closed errors visible via conntrack and in checkout's own trace spans calling "
        "oteldemo.ProductCatalogService/GetProduct). Exact code-level cause not confirmed -- this is "
        "reported with appropriately low confidence, not a fully-understood ground truth."
    )

    def inject(self) -> None:
        kubectl("rollout", "restart", "deployment/product-catalog", "-n", "otel-demo")
        kubectl("rollout", "status", "deployment/product-catalog", "-n", "otel-demo", "--timeout=90s")

    def teardown(self) -> None:
        kubectl("rollout", "restart", "deployment/checkout", "-n", "otel-demo")
        kubectl("rollout", "status", "deployment/checkout", "-n", "otel-demo", "--timeout=90s")

    def get_incident_description(self) -> str:
        return "The checkout service is experiencing a sudden increase in 5xx errors."
