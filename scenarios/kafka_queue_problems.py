from scenarios.base import FlagdScenario


class KafkaQueueProblemsScenario(FlagdScenario):
    name = "kafka_queue_problems"
    description = (
        "Kafka queue overload via the flagd kafkaQueueProblems flag: producers flood the "
        "orders topic and consumers add artificial delay, causing consumer lag to spike."
    )

    flag_name = "kafkaQueueProblems"
    injected_variant = "on"
    baseline_variant = "off"

    root_cause_service = "kafka"
    root_cause_type = "dependency_failure"
    ground_truth_summary = (
        "The kafkaQueueProblems feature flag was enabled, causing the Kafka orders topic to be "
        "overloaded with additional producer traffic while consumers (accounting, fraud-detection) "
        "add artificial processing delay. This results in growing consumer lag -- orders placed "
        "successfully via checkout but never processed downstream (no accounting records, no "
        "fraud checks). The symptom is async: checkout itself succeeds, but downstream processing stalls."
    )

    def get_incident_description(self) -> str:
        return (
            "The accounting service appears to have stopped processing new orders. "
            "Orders are being placed successfully but are not appearing in the accounting database. "
            "Fraud detection alerts have also gone silent."
        )


if __name__ == "__main__":
    import sys

    scenario = KafkaQueueProblemsScenario()
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
