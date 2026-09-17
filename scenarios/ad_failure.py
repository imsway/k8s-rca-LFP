from scenarios.base import FlagdScenario


class AdFailureScenario(FlagdScenario):
    name = "ad_failure"
    description = "Ad service fails all requests via the flagd adFailure flag."

    flag_name = "adFailure"
    injected_variant = "on"
    baseline_variant = "off"

    root_cause_service = "ad"
    root_cause_type = "application_error"
    ground_truth_summary = (
        "The adFailure feature flag was enabled, causing the ad service to fail every request. "
        "The frontend calls the ad service to display contextual advertisements; with it failing, "
        "ad slots are empty or error out. This is a non-critical-path failure -- checkout and "
        "cart functionality are unaffected, only the ad display is broken."
    )

    def get_incident_description(self) -> str:
        return (
            "Contextual advertisements are no longer appearing on the storefront. "
            "The ad slots on product and landing pages are empty. No other functionality appears affected."
        )


if __name__ == "__main__":
    import sys

    scenario = AdFailureScenario()
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
