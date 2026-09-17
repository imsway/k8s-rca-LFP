"""Scenario registry."""
from scenarios.ad_failure import AdFailureScenario
from scenarios.cart_failure import CartFailureScenario
from scenarios.kafka_queue_problems import KafkaQueueProblemsScenario
from scenarios.payment_failure import PaymentFailureScenario
from scenarios.recommendation_cache_failure import RecommendationCacheFailureScenario

CORE_SCENARIOS = [
    PaymentFailureScenario(),
    CartFailureScenario(),
    KafkaQueueProblemsScenario(),
    RecommendationCacheFailureScenario(),
    AdFailureScenario(),
]

SCENARIOS_BY_NAME = {s.name: s for s in CORE_SCENARIOS}
