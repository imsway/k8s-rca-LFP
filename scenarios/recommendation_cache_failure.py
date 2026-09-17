from scenarios.base import FlagdScenario


class RecommendationCacheFailureScenario(FlagdScenario):
    name = "recommendation_cache_failure"
    description = "Recommendation service cache failure via the flagd recommendationCacheFailure flag."

    flag_name = "recommendationCacheFailure"
    injected_variant = "on"
    baseline_variant = "off"

    root_cause_service = "recommendation"
    root_cause_type = "application_error"
    ground_truth_summary = (
        "The recommendationCacheFailure feature flag was enabled, causing the recommendation "
        "service's internal cache to fail. Every recommendation request now hits the underlying "
        "product-catalog service directly instead of serving from cache, increasing latency and "
        "load on product-catalog. The symptom is degraded frontend performance on pages that "
        "show product recommendations."
    )

    def get_incident_description(self) -> str:
        return (
            "The frontend is experiencing increased latency on product pages. "
            "Users report that pages with product recommendations are loading noticeably slower than usual."
        )


if __name__ == "__main__":
    import sys

    scenario = RecommendationCacheFailureScenario()
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
