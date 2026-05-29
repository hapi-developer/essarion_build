# Cloud infrastructure

- **Infrastructure as code, with a state file, in git.** Terraform / Pulumi / CloudFormation. Click-ops can boot a prototype; only IaC scales (review, audit, rollback, reproduce).
- **Least privilege on every IAM grant.** Each role has the minimum set of actions on the minimum set of resources. Default-deny; explicit allow. The `*` wildcard is a code smell.
- **Tag everything.** `Environment`, `Owner`, `CostCenter`, `Project`. Untagged resources turn into "what is this and can we delete it?" mysteries six months later.
- **Multi-AZ for stateful resources; multi-region only when the SLA demands it.** Multi-AZ is cheap; multi-region triples your operational complexity. Don't pay the cost without the requirement.
- **VPC layout: public / private / data subnets.** Public hosts NAT/ALB. Private hosts apps with egress to internet via NAT. Data subnets host DBs/queues with no internet. Cross-subnet via SG rules, never 0.0.0.0/0.
- **Secrets in Secrets Manager / Vault / GCP Secret Manager — never in env vars in the IaC.** Env vars from secret-fetch at boot time; IaC references the secret's ARN. Rotation policy on every secret.
- **Backups are not implementations until you've restored from them.** RTO/RPO are SLAs; test them quarterly. "We have backups" is a hope; "we restored prod from backup in 27 minutes during last quarter's drill" is a guarantee.
- **Limits are not warnings; they're outages.** Know your account-level limits (Lambda concurrent executions, EBS GP3 volumes per region, etc.). CloudWatch / billing alerts at 70% and 90%.
- **Egress is a billing surprise.** Cross-region, cross-AZ, and internet egress are billed differently and most teams discover the rates the hard way. Architect for locality; use VPC endpoints / PrivateLink where they apply.
- **Cost is a SLO.** Track $/request, $/customer; alert when they move. The cheapest way to find a runaway is when finance asks; the better way is a monthly cost-aware deploy review.
- **Disaster recovery has tiers.** Pilot light, warm standby, multi-region active-active are increasingly expensive and increasingly fast. Pick the tier to match the business need, not the engineering pride.
- **Immutable infrastructure: replace, don't patch.** New AMI / image / version → roll new instances → drain old ones. SSH-into-a-host-to-fix-it is a runbook smell.
