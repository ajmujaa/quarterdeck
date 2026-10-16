Reading AWS infrastructure files (Terraform, CDK, CloudFormation and SAM, Serverless Framework). You see files, not the account: say what the files would do, never what is running.

**Replacement and deletion (look here first)**
- Terraform: renaming a resource address without a `moved` block destroys the old resource and creates a new one. Changing `bucket` (S3), a DynamoDB table `name` or `hash_key`, or toggling `storage_encrypted` on an RDS instance forces a new resource. A new resource is empty.
- CloudFormation, SAM, CDK: changing a logical ID creates a new resource and deletes the old one. In CDK the logical ID comes from the construct path, so renaming or moving a construct does this silently. Setting a custom physical name (`TableName`, `BucketName`, `DBInstanceIdentifier`) on an existing resource usually means replacement.
- Stateful resources: RDS, DynamoDB, S3, KMS keys, EFS, Cognito user pools, queues with messages. Check for `prevent_destroy`, `deletion_protection`, `DeletionPolicy` and `UpdateReplacePolicy` (Retain or Snapshot), `RemovalPolicy.DESTROY`, `autoDeleteObjects: true`, `skip_final_snapshot = true`. Any of the unsafe settings on stateful data is a decision for a person. A KMS key scheduled for deletion makes everything encrypted with it unreadable.
- Removing a resource block deletes the real resource on the next apply or deploy.

**IAM**
- Flag `Action: "*"` or `service:*`, `Resource: "*"`, and `iam:PassRole` on `*`; each needs a stated reason in the file.
- Flag `AdministratorAccess`, `iam:*`, and permissions that let a role grant itself more (`iam:CreatePolicyVersion`, `iam:AttachRolePolicy`, `iam:PutRolePolicy`).
- Trust policies: a Principal of `*`, or another account's root, without a Condition (such as an external ID or source ARN), lets others assume the role.
- Prefer one role per function or service, scoped to named ARNs. In the Serverless Framework check `provider.iam.role.statements`.

**Exposure**
- Security groups: ingress from `0.0.0.0/0` or `::/0`, above all on 22, 3389 and database ports (3306, 5432, 1433, 27017, 6379), or protocol `-1` (all traffic).
- RDS or OpenSearch with `publicly_accessible = true`; public subnets or `map_public_ip_on_launch`; internet-facing load balancers that nothing needs.
- S3: all four Block Public Access settings on; no `public-read` ACL; no bucket policy with `Principal: "*"` unless a Condition limits it; a deny on `aws:SecureTransport = false`.
- API Gateway routes with authorization NONE, Lambda function URLs with auth type NONE: confirm the endpoint is meant to be public.

**Encryption and secrets**
- At rest: RDS `storage_encrypted`, EBS `encrypted`, SQS and SNS with a KMS key, log groups and buckets holding sensitive data. In transit: HTTP listeners without a redirect to HTTPS, CloudFront viewer protocol `allow-all`, old TLS policies.
- No secret in a `.tf`, a variable default, a committed `*.tfvars`, a template parameter without `NoEcho`, or a plain Lambda environment variable. Use Secrets Manager or SSM Parameter Store (SecureString) and pass the reference. A password written in Terraform also lands in the state file in clear text.

**Serverless functions**
- Timeout (Lambda maximum is 900 s; a REST API integration times out at 29 s by default), memory, reserved concurrency (0 stops the function; a value also takes from the account's shared pool), provisioned concurrency (costs while idle).
- Failure paths: a dead-letter queue or on-failure destination for async and queue-triggered functions; batch size and retry settings on event source mappings.
- A function in a VPC reaches the internet only through a NAT gateway.

**Blast radius across environments**
- Environments should be separated by account or at least by state. One state or backend shared by dev and prod, a stage name defaulting to prod, resource names that collide across stages, or a changed backend (a state migration) widen the blast.
- Hard-coded account IDs, ARNs and regions are assumptions: say which.
- Tags: `default_tags` or stack tags for owner and environment; missing tags are low risk unless the project requires them.

**Cost traps**
- NAT gateways (hourly plus per GB, one per AZ), provisioned IOPS and DynamoDB provisioned capacity, Multi-AZ doubling, always-on OpenSearch and ElastiCache, idle load balancers.
- Log groups default to never expiring: look for `retention_in_days` or `RetentionInDays`.

**Reading the diff**
- Start at deletions and renames, then IAM and security group blocks, then stateful resources, then everything else. An unchanged-looking block can be new because its name changed.
- A module or variable change can touch many resources: follow the reference and say how many.
- For each item say how to roll back from the files, and when the answer is that you cannot (deleted data, rotated or deleted key), say so plainly.
