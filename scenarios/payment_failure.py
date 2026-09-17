from scenarios.base import FlagdScenario


class PaymentFailureScenario(FlagdScenario):
    name = "payment_failure"
    description = "Payment service fails 100% of charge requests via the flagd paymentFailure flag."

    flag_name = "paymentFailure"
    injected_variant = "100%"
    baseline_variant = "off"

    root_cause_service = "payment"
    root_cause_type = "application_error"
    ground_truth_summary = (
        "The paymentFailure feature flag was set to 100%, causing the payment service to reject every "
        "charge request. This surfaces as checkout failures (5xx) since checkout calls payment "
        "synchronously as part of placing an order."
    )

    def get_incident_description(self) -> str:
        return "The checkout service is experiencing a sudden increase in 5xx errors."

    def verify_symptom(self) -> bool:
        """Verify the failure manifests by calling payment's Charge RPC directly."""
        payload = {
            "amount": {"currency_code": "USD", "units": 100, "nanos": 0},
            "credit_card": {
                "credit_card_number": "4432-8015-6152-0454", "credit_card_cvv": 672,
                "credit_card_expiration_year": 2039, "credit_card_expiration_month": 1,
            },
        }
        output = self.grpc_call("payment:8080", "oteldemo.PaymentService/Charge", payload)
        return "ERROR" in output and "transactionId" not in output


if __name__ == "__main__":
    import sys

    scenario = PaymentFailureScenario()
    action = sys.argv[1] if len(sys.argv) > 1 else "inject"
    if action == "inject":
        print(f"Injecting {scenario.name}...")
        scenario.inject()
        print("Done. Incident description:", scenario.get_incident_description())
    elif action == "teardown":
        print(f"Tearing down {scenario.name}...")
        scenario.teardown()
        print("Done.")
    else:
        print(f"Unknown action '{action}'. Use 'inject' or 'teardown'.")
        sys.exit(1)
