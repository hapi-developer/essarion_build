# Event-driven design

- **Events represent things that *happened*, not commands to do.** `OrderPlaced`, not `PlaceOrder`. Commands carry intent (and can be rejected); events are immutable history (and are facts you must absorb).
- **Schemas are forever.** Once an event is published, consumers depend on its shape. Add optional fields freely; never remove or rename. Version the schema (`OrderPlaced.v1`, `.v2`) when a breaking change is unavoidable.
- **Idempotent consumers, always.** Brokers redeliver under at-least-once. Consumers must dedupe by an event ID or be naturally idempotent (e.g., upsert by primary key).
- **Ordering only inside a partition.** Kafka, Kinesis, Pub/Sub all guarantee order per partition (or per key) — not globally. Partition by the entity whose ordering matters: `order_id`, `user_id`.
- **Outbox pattern for transactional publish.** If "write to DB" and "publish event" must succeed together, write the event to an `outbox` table in the same transaction; a separate process drains it to the broker. Reliable; idempotent; survives restarts.
- **Don't read your own writes via the event stream.** If service A needs to act on its own writes, do it locally then publish. Round-tripping through Kafka adds latency *and* couples your service to the broker's recovery time.
- **DLQ + alerting + tooling to replay.** A bad event poisons a partition until you skip or replay it. Dead-letter queue, an alarm, and a documented runbook are baseline.
- **Eventual consistency is a UX problem.** Decide where it's hidden (optimistic UI, "estimated" totals) and where it must be exposed ("your transfer will appear within a minute"). Don't pretend consistency is immediate.
- **Saga over distributed transactions.** Coordinate multi-service business processes by chained events + compensating actions. 2PC across services is fragile and slow.
- **Observability per topic: lag, throughput, error rate.** Consumer lag is the leading indicator. A growing lag and a flat throughput means a stuck consumer.
- **Backpressure: slow consumers can't slow producers.** Either drop, queue with bounded memory, or scale consumers. Unbounded queues are an OOM waiting to happen.
