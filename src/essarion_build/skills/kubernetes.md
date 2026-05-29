# Kubernetes

- **Resource requests and limits on every container.** Without requests, the scheduler can't reason about packing — pods get evicted under pressure. Without limits, a memory leak takes down the node.
- **Liveness ≠ readiness.** Liveness: "kill me if I'm wedged." Readiness: "stop sending me traffic; I'm not ready yet." Conflating them causes traffic loss during slow starts and stuck-pod cascades during partial failures.
- **`replicas: 1` is not high availability.** Even for "this rarely gets traffic" services — node maintenance, pod evictions, image pulls all cause outages. `replicas: 2 minimum` for anything user-facing; PodDisruptionBudget to keep them up during voluntary disruptions.
- **Rolling updates need `maxUnavailable: 0`, `maxSurge: 1` for low-replica deployments.** With 2 replicas and `maxUnavailable: 1` you serve from one pod during deploys.
- **Graceful shutdown with `preStop` + `terminationGracePeriodSeconds`.** Pod gets `SIGTERM` → finish inflight requests → fail readiness → drained from the load balancer. Without it, you 502 on every deploy.
- **ConfigMaps for non-secret config; Secrets for secrets.** Both are first-class resources, scoped to a namespace, versioned. Pod restarts on change (or use a sidecar/operator that watches).
- **Namespaces are a hierarchy not a flat list.** `team/env/service` works; flat `prod-frontend` does not when you grow past 100 services. Use labels for orthogonal slicing (env=prod, team=billing).
- **Cluster autoscaler + HPA for the easy wins; VPA when memory grows over time.** Cap autoscaler max to your budget; otherwise a memory leak scales horizontally to infinity.
- **`kubectl exec` and `kubectl logs` are debugging, not operations.** If you need to ssh into a pod to know what's going wrong, you don't have enough observability. Logs structured + metrics + traces beat shell access every time.
- **CRDs for genuine extension; not as a "let's make a yaml DSL" project.** Adding an operator means owning its upgrades, RBAC, leader election, and CRD migrations forever.
- **Network policies are deny-by-default once you turn them on.** Test in a non-prod namespace first; a policy that accidentally drops sidecar→app traffic kills everything.
- **Storage classes are forever.** Once a PV is created with a class, you can't change it. `gp3` over `gp2`, `Premium_LRS` over `Standard_LRS` where the workload justifies; pick before you have data, not after.
