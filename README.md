# Technical Write-up: K8s RCA Agent

## Architecture

Three-node LangGraph state machine running on a local kind cluster:

```
START -> TRIAGE -> INVESTIGATE (loops) -> SYNTHESIZE -> END
```

**TRIAGE** is pure Python -- no LLM call. It pulls pod statuses, K8s events, Prometheus alerts, and active feature flags from the flagd ConfigMap. Same sweep every time, so there's no decision for a model to make here.

**INVESTIGATE** is the LLM-driven loop. Each iteration, the model reads existing evidence, calls 2-4 tools in parallel (ThreadPoolExecutor), and emits a structured `InvestigationUpdate` with its current hypotheses and confidence. The loop continues until the model sets `ready_to_conclude = true` or we exhaust the turn/tool-call budget.

**SYNTHESIZE** forces the output through `with_structured_output()` into a Pydantic model, so the report always has the required fields -- root cause, evidence, timeline, confidence, alternatives, uncertainty.

We originally had 5 nodes (separate reason, investigate, evaluate steps) but merged them into a single LLM call per turn. The model handles tool calling and hypothesis updates together, which cuts per-turn cost in half without any quality loss.

The target app is the OpenTelemetry Astronomy Shop (Helm chart v0.41.1), trimmed to fit on a 16GB machine by disabling its AI chatbot components and swapping OpenSearch for Loki.

## Agent Design

The agent uses Gemini 3.1 Flash-Lite as primary LLM (free tier) with Groq as automatic fallback via LangChain's `.with_fallbacks()`. Model names are configurable through env vars because Google renamed the model at least once during development.

Investigation state is carried in a LangGraph `TypedDict`. Key fields: `messages` (conversation), `hypotheses` (list of named hypotheses with status/confidence/evidence), `tool_calls_used` (budget tracking), `iteration` (turn counter). The routing function checks `ready_to_conclude` and budget limits to decide whether to loop or synthesize -- no extra LLM call for routing.

Context management prunes older messages to avoid blowing through the context window. We keep the system prompt, initial triage dump, and the N most recent turns. Older turns collapse into one-line summaries of which tools were called (so the agent doesn't repeat queries) with full results dropped.

## Tooling Approach

18 tools across 4 backends, all registered through a central wrapper in `registry.py`:

| Backend | Tools | Examples |
|---|---|---|
| Kubernetes API | 8 | pod statuses, logs, events, configmaps, deployments, services, nodes |
| Prometheus | 4 | instant query, range query, alerts, scrape targets |
| Loki | 2 | log query, service name listing |
| Jaeger | 4 | services, operations, trace search, trace detail |

The wrapper adds audit logging (args, timing, result), error containment (exceptions become JSON error payloads instead of crashing the loop), transient retry (2 attempts with 1s delay for network errors), and output truncation with tiered limits (3K for compact data, 6K for logs, 8K for trace spans). The tiered limits were important -- a flat 2K cap was cutting trace span trees mid-evidence, so the agent could see errors existed but couldn't identify which service failed.

## Observability Sources Used

| Source | What It Gives Us |
|---|---|
| Kubernetes API | Pod health, restart counts, events (OOMKilled, CrashLoopBackOff), resource configs, ConfigMaps |
| Prometheus | Error rates, latency percentiles, CPU/memory, scrape target health |
| Loki | Application logs with `service_name` labels (via OTel Collector OTLP export, not file scraping) |
| Jaeger | Distributed traces, service-to-service call chains, latency breakdowns, feature flag span attributes |

Every scenario we tested needed evidence from at least 2-3 sources. Payment failure, for example, shows up as a ConfigMap change (flag), trace errors on payment charge spans (Jaeger), and a checkout error rate spike (Prometheus). No single source tells the full story.

## How the Agent Investigates Incidents

1. **Triage** gathers a broad snapshot -- all pod statuses, recent events, firing alerts, and any active feature flags. This runs without an LLM call.

2. **Investigation loop** -- the LLM gets the triage dump and decides what to dig into. It picks tools, reads results, and updates its hypothesis list each turn. Tools run in parallel when there's no dependency between them. The model sees its full hypothesis state (what it's considering, what confidence it has, what evidence supports/contradicts each theory) every turn, which helps it decide what to investigate next rather than retreading ground.

3. **Synthesis** -- when the model decides it has enough evidence (or the budget runs out), it produces the final report: root cause identification, supporting evidence, timeline reconstruction, confidence score with justification, alternative explanations with reasons they were ruled out, remaining uncertainty, and recommended actions.

The agent typically uses 8-15 tool calls across 3-5 investigation turns per scenario. Budget defaults are 30 tool calls and 8 turns, which is more than enough.

## How Hypotheses Are Handled

Every investigation turn, the model emits an `InvestigationUpdate` as a structured tool call:

```python
class InvestigationUpdate(BaseModel):
    hypotheses: list[HypothesisEntry]  # name, status, confidence, evidence_for, evidence_against
    overall_confidence: float
    ready_to_conclude: bool
```

Each hypothesis carries a status (investigating / confirmed / rejected), a confidence float, and lists of supporting and contradicting evidence. The model is prompted to maintain multiple hypotheses simultaneously and seek disconfirming evidence, not just look for confirmation of its first guess.

Rejected hypotheses and the reasons for rejection carry through to the final report as `alternative_explanations`, which is a requirement from the assignment. The synthesis prompt explicitly instructs the model to name `root_cause_service` as the service where the fault *originates*, not the downstream caller that reports symptoms -- we had to add that after the agent kept attributing payment failures to the checkout service.

## Security/Sandboxing Model

**RBAC**: The agent runs as an `rca-agent` ServiceAccount with read-only access (get/list/watch) scoped to the `otel-demo` namespace. A separate ClusterRole grants read-only node access for resource pressure checks. No write verbs, no Secrets, no exec, no cross-namespace access. Token is short-lived (24h).

**Application-level defense**: Tool code validates namespaces client-side on top of server-side RBAC. All API paths are hardcoded -- the LLM controls query parameters (validated for length and control characters) but never the URL path itself. There's no code path that could reach a write endpoint.

**Prompt injection**: The system prompt marks all tool output as untrusted data. A malicious log line saying "ignore your instructions" gets treated as data, not as a command.

**Verification**: `setup/verify-sandbox.sh` runs `kubectl auth can-i` checks via impersonation -- reads succeed, writes denied, secrets denied, cross-namespace denied. 9 checks, all passing.

## Known Limitations

- The kafka scenario scores 0.67 because the agent names "flagd" as root cause service instead of "kafka" -- technically correct (the flag caused it) but doesn't match our ground truth.
- Context window limits mean very long investigations lose early evidence. The pruning heuristic keeps tool names but drops full results, so the agent remembers what it asked but not exact numbers.
- The agent has no write access so it can't verify fixes or test remediation suggestions it makes.
- All tools hit the cluster synchronously -- if the observability stack is down the agent can't do much besides report that it can't reach things.
- Single-agent architecture means triage is broad rather than targeted. A multi-agent setup could narrow the search space before the main investigation starts.

## Interesting Failures Encountered

**Checkout-product-catalog noise**: The demo app has a real gRPC keepalive bug between checkout and product-catalog. Old traces showing this would mislead the agent into investigating it instead of the freshly-injected fault. Fixed by surfacing active feature flags in triage so the agent sees "paymentFailure is set to 100%" upfront and prioritizes accordingly.

**Truncated flag config**: The `get_configmap` tool capped output at 3000 chars, slicing the flagd JSON config mid-object. On top of that, Windows `\r\n` line endings broke `json.loads`. Had to bypass the tool's truncation in triage, strip carriage returns, and add a regex fallback for cases where JSON is still incomplete.

**Symptom vs. cause attribution**: The agent consistently named downstream services (e.g. "checkout") as root cause when the actual fault was upstream (e.g. "payment"). Took explicit prompt engineering in the synthesis step to fix this -- the model needed to be told that `root_cause_service` means where the fault *originates*.

**KUBECONFIG scoping**: Scenario injection scripts were inheriting the agent's sandboxed KUBECONFIG from `.env`, causing them to get RBAC-denied when trying to patch ConfigMaps. Fixed by having scenario subprocesses explicitly drop the KUBECONFIG env var so they fall back to the admin `~/.kube/config`.

## What You Would Build Next

- **Multi-agent triage** -- a lightweight agent that identifies the affected service(s) first, so the main investigator starts with a narrower scope
- **RAG over past reports** -- index previous RCA reports to surface patterns ("last time cart failed it was also a flagd flag")
- **Confidence calibration** -- use eval results to tune the model's confidence scores so 0.9 actually means "right 90% of the time"
- **Remediation mode** -- a separate write-scoped ServiceAccount that can restart pods or roll back deployments, activated only with explicit operator approval
- **Alertmanager integration** -- trigger investigations automatically from firing alerts instead of requiring manual incident descriptions
