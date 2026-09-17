from scenarios.base import FlagdScenario


class CartFailureScenario(FlagdScenario):
    name = "cart_failure"
    description = "Cart service fails 100% of requests via the flagd cartFailure flag."

    flag_name = "cartFailure"
    injected_variant = "100%"
    baseline_variant = "off"

    root_cause_service = "cart"
    root_cause_type = "application_error"
    ground_truth_summary = (
        "The cartFailure feature flag was set to 100%, causing the cart service to fail every "
        "request. This breaks adding items to cart and viewing the cart, and also blocks "
        "checkout (which reads the cart as its first step)."
    )

    def get_incident_description(self) -> str:
        return (
            "Users are reporting they cannot add items to their cart or view their cart contents. "
            "The frontend shows errors when interacting with shopping cart functionality."
        )


if __name__ == "__main__":
    import sys

    scenario = CartFailureScenario()
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
