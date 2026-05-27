# Observability

Three pillars, used together:

- **Logs** — discrete events. Best for "what happened in this request?" Structured (see `logging`).
- **Metrics** — numeric aggregates over time. Best for "is the system healthy right now?" Counters, gauges, histograms. Low cardinality on labels.
- **Traces** — causally-linked spans across services. Best for "where did the latency come from?" One trace per logical request, propagated via headers (`traceparent`).

Practical rules:

- **Cardinality kills metrics.** A label like `user_id` produces millions of unique time series — the storage costs explode. Keep labels to enums and bounded sets (status code, endpoint name, region). User IDs belong in logs/traces, not metric labels.
- **Use histograms, not averages.** P50, P95, P99 latency tells you the user experience. Average latency hides tail problems.
- **Golden signals: latency, traffic, errors, saturation.** Track all four for every service. The SRE book is right about this.
- **RED for services, USE for resources.** Requests, Errors, Duration (services); Utilization, Saturation, Errors (CPUs, disks, queues).
- **SLOs over SLAs.** Define what "fast enough" and "available enough" mean for *each user-facing journey*. Alert on SLO burn rate, not raw error count — that filters noise.
- **Alert on symptoms, not causes.** Page when users are affected (error rate up, latency over SLO). The cause (CPU at 100%) is something you investigate after.
- **Sample traces.** 100% of traces is expensive and rarely useful. Tail-sampling (keep slow/error traces, sample success traces at 1%) gives the best signal-to-cost ratio.
- **One dashboard per service per audience.** Engineers want detail; on-call wants the one screen that tells them "is anything broken right now?"

Without observability, debugging production is archaeology.
