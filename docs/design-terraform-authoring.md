# Design: writing and updating Terraform, behind a plan gate

Status: proposal. No code exists for this. It is a design for review.

Today the `infra` duty (`duties/infra.sh`) reads a change to infrastructure files and writes a report. It never runs anything against a cloud and holds no cloud credentials. This document adds the other half: Quarterdeck helps write and update Terraform, with the same limits. The model edits `.tf` files in a throwaway worktree. A person reads the result and applies it. Nothing in Quarterdeck ever runs `terraform apply`.

## What is decided

- **The flow is the existing plan-gated flow, with one new kind of item.** The planner writes an item for an infrastructure change. Its **Where** field names the folder (and only that folder) that may change. The shipwright edits `.tf` files there. The harness validates. The infra agent reviews against the AWS pack. The project's own CI produces the plan text. A person applies.
- **Nothing runs against a cloud from Quarterdeck.** No `apply`, no `plan` with real credentials, no `init` that talks to a registry with the owner's credentials, no state access. The infra duty's rule "no credentials, ever" is kept and extended to this flow.
- **The Where field is the only thing that unlocks a path.** As in `bin/protect.py`, the field is read only from its structured line, and it can never unlock the always-protected paths (CI workflows, `.claude/**`, and the rest of that list). A plan's prose and an issue's text unlock nothing.
- **Validation runs in the sandbox with no cloud access and no network.** Formatting and `terraform validate` with providers already present, or a refusal that says why not (below).
- **The plan text comes from the project's own CI** and returns as untrusted data, wrapped by `untrusted()`, like a review comment or CI output does today.
- **A person applies.** Always. The harness does not offer an apply button, a command to copy, or a pull request that applies on merge unless the project already has that in its own pipeline, which Quarterdeck neither creates nor changes.
- **Large projects are worked one module at a time,** with a size budget, and a change that does not fit is split or handed back as `NEEDS_HUMAN`.
- **Pack text is versioned,** and a report names the pack version it was judged against.
- **Out of scope:** drift detection and applying.

## What the owner must decide

1. Whether the project's CI plan should be fetched by Quarterdeck at all in the first release, or whether a person pastes the plan text into the item. Fetching needs a read of CI output through the harness (GitHub, which the harness already does for CI results); it holds no cloud credential. Recommendation: fetch CI output, never run the plan.
2. Whether `terraform validate` may run when providers are not installed. Validation needs the provider schemas, and getting them needs network access that the sandbox does not give. Options: (a) accept `terraform fmt -check` plus a syntax parse only; (b) allow a separate, owner-approved `init` step on a provider cache folder (the install mode of the sandbox, which has the network, exists for package installs); (c) require the project to commit a lock file and a provider mirror. Recommendation: start with (a), add (b) as an explicit per-project setting.
3. Which files count as infrastructure the shipwright may touch: `.tf` and `.tfvars.example` only (recommended), or also `.tfvars`, `backend` blocks, lock files, workflow files. Recommendation: `.tf` only, with `.terraform.lock.hcl` changed only by a person.
4. The size budget numbers (suggested values below).
5. Whether a state backend change, a provider upgrade or a module source change is ever allowed through this flow. Recommendation: no, always `NEEDS_HUMAN`.
6. Who the pack's reviewer is. The AWS pack says it was "not reviewed by an AWS specialist"; a flow that writes infrastructure raises the cost of a gap in that pack.

## The flow, step by step

```
issue or request
   |
planner      writes the item: what, why, Where (the folder), the check to run
   |
(person)     reads the plan, approves the item
   |
shipwright   edits .tf files in a throwaway worktree, only under Where
   |
harness      model_diff_gate: protected paths, outside-Where changes -> refused
   |
harness      terraform fmt -check and validate in the sandbox, no network, no credentials
   |
infra        reads the diff and the files against the AWS pack -> change report
   |
branch/PR    pushed by the harness, as for any shipwright change
   |
project CI   produces the plan text (its own job, its own credentials, read only)
   |
harness      brings the plan text back as untrusted data; infra reads it as well
   |
person       reads the report and the plan, applies through the project's own process
```

### 1. The planner item and the Where field

The planner (`duties/planner.sh`) already writes ruling items with a structured line, `**Where.** \`path\``. `bin/protect.py` reads exactly that line and nothing else: a list, an unquoted value, or a second Where line unlocks nothing.

For Terraform the Where value is a **folder**, written with a trailing slash, for example `infra/network/`. The rule, new but small:

- A Where ending in `/` names a folder; every file under it may change, subject to the always-protected list. A Where without a slash names one file, as today.
- The folder must exist in the checkout and be inside the project. A folder containing `..`, an absolute path, or a link out is refused.
- One folder per item. A change that needs two modules is two items, in order. This keeps blast radius, review and rollback per module and matches how Terraform state is usually split.
- The planner is told, in its prompt, to name the folder of the **root module** the change belongs to if the change is an edit to a child module, so that the person sees which state it will reach. When the child module is shared, the item says which callers are affected (the planner reads the callers; the shipwright does not need to).

The item also carries the check line the shipwright must satisfy: format clean, validate clean, and "no resource removed or renamed unless the item says so". The last condition is the single most useful line against the replacement traps listed in the AWS pack.

### 2. The shipwright edits

The shipwright runs as any builder does: a throwaway worktree, Edit and Write limited to the worktree, a few named commands only, the OS sandbox on when a shell is present. For this flow:

- Its tool list has Read, Grep, Glob, Edit, Write and no shell. The harness runs format and validate itself (step 3). A builder that cannot run `terraform` cannot be talked into running `terraform apply`, and it has no network.
- Its prompt includes the item, the Where folder, the matching pack text (so it knows which edits are dangerous before it makes them), and a standing instruction: prefer `moved` blocks to renames, never remove `prevent_destroy`, `deletion_protection` or a retention setting, never write a secret value into a file, use references to a secret store, never edit a `backend` block.
- It returns the existing contract (`RESULT: FIXED ...`, `NEEDS_HUMAN ...`, `NO_CHANGE ...`).
- After it stops, `model_diff_gate` runs as today: any change outside the Where folder, or to an always-protected path, is refused before any check.

Additional gates for this flow, in the same place (new rules in `bin/protect.py`, small):

- A change that touches a `terraform { backend ... }` block, a `required_providers` version, or a module `source` is refused unless the item names it in plain words in its structured fields (not in prose).
- A change that adds a `provisioner`, `local-exec`, `remote-exec`, an `external` data source, or an `http` data source is refused. These run code on the machine that plans or applies. This is the Terraform version of the rule that already stops a model from editing a `package.json` script.
- A change that deletes a resource or data block, or changes a resource address, is allowed only if a `moved` block accompanies it or the item says deletion is intended. The check is on the parsed result, not on the model's words.

### 3. Validate in the sandbox

The harness runs, through `project_exec` (check mode: scratch home, minimal environment, no network except loopback, private files unreadable, writes only in the worktree):

1. `terraform fmt -check -recursive` on the Where folder.
2. A syntax and reference check: `terraform validate`, if providers are available (see decision 2), otherwise a parse-only check, which the report says is weaker.

Rules that make this safe:

- **No credentials.** The environment is the minimal one `px_prepare` already builds. The infra duty already unsets every cloud, Terraform and tooling variable from its environment (`AWS_`, `TF_`, `ARM_`, `GOOGLE_`, and the rest); the same list applies here.
- **No backend.** Validation is run with the backend disabled (`terraform init -backend=false`, when an init is allowed at all). No state file is read or written. If a state file or a variable file with values is in the folder, it is named and never opened, as the infra duty does today.
- **No providers are downloaded from inside the model's reach.** If provider schemas must be fetched (decision 2b), that step is a separate harness step in install mode, run from the lock file only, before the model has run, and never after a model edit that touched the lock file or a provider requirement.
- A failing check goes back to the shipwright once, with the output wrapped as untrusted (it can quote file contents the model wrote), within the existing retry rules. A second failure is `NEEDS_HUMAN`.

This is not a plan. `validate` says the files are consistent. It does not say what would change in an account.

### 4. The infra agent reviews

The `infra` duty runs on the worktree's diff exactly as it does for a pull request today (`--diff main` form): it finds the infrastructure files, bounds the diff and text, picks the packs that fit (`bin/packs.py`: the AWS pack matches Terraform with an AWS deploy target), and the rigger seat returns the contract `INFRA_JSON` with `resource`, `change`, `risk`, `why`, `blast_radius`, `rollback`, `needs_human`.

What this flow adds:

- The reviewer is a different call from the shipwright, with a different prompt and, where the owner chooses, a different model or provider seat (see [design-providers.md](design-providers.md)).
- The report's harness-written footer already says it cannot see the live account. In this flow it also says "no plan was run by Quarterdeck".
- Any item with `needs_human: true`, or a risk of high, stops the flow at the person. The branch is still pushed so it can be read, but the item is not marked ready.
- The report names the pack version (below).

### 5. The project's own CI produces the plan

Quarterdeck does not plan. The project's CI does, using the project's own credentials, which should be read-only for a plan job. This is a separation the project must already have to be safe. The design depends on three facts:

1. A plan job runs on the pushed branch (usually on pull request). Its credentials belong to the CI system and are never given to Quarterdeck.
2. The harness reads the job's output the way it reads any CI result: through the GitHub API, as text.
3. **The plan text is data written by a process that ran model-influenced code.** A resource name, a tag value, a description or an error message in it can carry any text, including instructions. It enters a prompt only through `untrusted()`, with a label such as `terraform plan output`, and the infra duty is told in its prompt that it is data. It also passes the output scan before it is quoted anywhere the harness posts: a plan can contain values from state that are secrets by mistake. The scan is pattern based (Gap G13) and does not make that safe, so the report only quotes counts and resource addresses from the plan, never value lines. The person reads the plan in CI, not in a Quarterdeck comment.

What the harness extracts from the plan text, by its own parsing and not the model's: the counts of resources to add, change, destroy and replace, and the addresses of the destroyed and replaced ones. If the project's CI can output the plan as JSON (`terraform show -json`), the harness reads that file's `resource_changes` list instead of parsing text. The extracted numbers are compared with the infra report: a destroy or replace in the plan that the report did not list is shown first, as "the plan shows a change the review did not mention".

The CI plan job is the project's. If the project has none, the report says "no plan available" in the harness's words, and the item cannot be marked ready for apply.

A plan from a fork's branch is never fetched or read for this flow, as for other duties (`fork_refuse`).

### 6. A person applies

The final step has no Quarterdeck action. The item shows: the change report, the pack version, the plan counts, a link to the CI run, and the sentence "apply through your own process". The harness does not hold a credential able to apply, does not generate an apply command, and does not trigger an apply workflow (the same rule as: the harness never touches a workflow file).

A person can still be helped to apply: the report lists the order of modules when several items touch one stack, what to look at in the plan first (destroys, replacements, IAM, ingress), and the rollback line from the infra report.

## Large projects

Terraform repositories are often large: many modules, many environments, thousands of lines.

- **Per-module scope.** One item, one folder. The infra duty's existing caps apply per run (40 files, 60,000 characters of diff, 100,000 of text, 30,000 for one file). For this flow they are set per folder and a folder over the budget is not truncated silently: the report says "only the first N files were read" and the item is `NEEDS_HUMAN`.
- **Size budget (suggested):** a single item may change at most 15 files and 600 added lines in the Where folder. Over that, the planner is told to split. Numbers to confirm with the owner.
- **Finding the right folder.** For a request that does not name a place, the planner reads a harness-built index, not the whole tree: a list of folders that hold `.tf` files, with the first lines of each folder's `README` or the module's `description` if present, and the names of the modules that call it. The index is built by the harness from the files (like the project scan in `bin/scan.py`), and is bounded.
- **Shared modules.** A child module change reaches every caller. The item names the callers, and the review lists them under blast radius. The CI plan for each affected root is needed; the report says which roots have a plan and which do not.
- **Environments.** If dev and prod share a folder through variables, the item says which environment the change is meant for, and a change that would also apply to prod is `needs_human` with high risk. The AWS pack already lists shared state and defaulting-to-prod stage names as exposure.
- **Generated and vendored code.** `.terraform/`, downloaded modules and provider caches are never read or edited. The secret screen and the Where rule already keep them out.
- **Cost of a run.** One item is one shipwright call and one infra call. Per-call and daily budgets apply unchanged.

## Pack versioning

The AWS pack (`packs/aws/pack.json` and `knowledge.md`) is the reviewer's checklist. For this flow it matters more, since a model may now write what the pack judges.

- Add `version` (a date or a number) and `reviewed` (who and when, or "not reviewed by a specialist") to `pack.json`. The existing `tested` text already records what was and was not tested; keep it and keep it honest.
- The infra report and the run ledger row record the pack name and version used. A later pack change does not rewrite an earlier verdict.
- A pack change that adds or removes a check is a code change: it needs the pack's fixture run (`fixtures/infra/`) and the result written in `tested`.
- Terraform-specific additions to test before this flow ships: `moved` and `removed` blocks, `lifecycle` (`prevent_destroy`, `ignore_changes`, `create_before_destroy`), `for_each` key changes that replace resources, `count` to `for_each` migrations, `import` blocks, provider version bumps, workspaces, and data sources that read live values.
- The pack tested "modules over many files" as NOT tested. That has to be tested with the module fixtures before the shipwright is allowed to write them. This is the first step of the plan below.
- Provider version facts in the pack (for example which attribute forces replacement) change with provider releases. The pack should say "as of provider version X" where it states one, and the doctor warns when the pack is older than a set age (suggested: 180 days).

## What stays out of scope

- **Applying.** Quarterdeck never applies, never holds the credentials to apply, and does not trigger it.
- **Drift.** Comparing files with the live account needs read credentials for the account and state. That is a different product with a different threat model. The infra report already says it cannot see drift. Nothing here changes that.
- **State.** No reading, moving, importing, or locking of state. A `terraform import`, `state mv` or `state rm` is an operation on live state and is a person's.
- **Creating the CI plan job** or any workflow file. Workflow files are protected paths. If the project has no plan job, the report says so.
- **Other tools** (CDK, CloudFormation, SAM, Serverless, Pulumi, OpenTofu-specific features). Terraform syntax only; OpenTofu is close enough that the same flow probably works, which is **unverified** here.
- **Cost estimates** from a pricing service. The pack's cost traps are the only cost reasoning.
- **Policy engines** (Sentinel, OPA, Checkov, tfsec). A project's own may run in its CI; their output enters as untrusted data like the plan. Running them in the sandbox is possible later and is not part of this design.

## Test plan

Same style as the rest of the repository: tests that fail before the code exists.

1. Fixtures: a small Terraform project with an S3 bucket, an IAM role, a security group, a database and one shared module with two callers. Planted mistakes for the shipwright to be tempted by (a rename without `moved`, a removed `prevent_destroy`, a world-open ingress, a `local-exec` provisioner, a backend edit). The model-free tests use a stand-in shipwright that makes each planted edit and check that the gate refuses it.
2. `bin/protect.py` tests for the folder form of Where, for a Where that tries to escape, for a second Where line, and for a plan prose that names a path.
3. A test that the validate step runs with no cloud variable, no network and no readable private file (the existing sandbox probes, run on the Terraform command).
4. Injection: the plan-output fixture. Hostile text in a resource name, a tag and an error line, through `untrusted()`, against the infra duty, added to `injection/fixtures.py` as a new place. Run the structural check always and the real-model run before release, as in the injection report.
5. The infra duty on a module fixture with many files, to replace the "not tested" in the pack.

## Plan, in small steps

1. Test the AWS pack on a multi-file module fixture and write the result in `tested`. Add `version` and `reviewed`.
2. Add the folder form of Where to `bin/protect.py` with its tests.
3. Add the Terraform gates (backend, provider and module source, provisioners and external data, deletes without `moved`) with tests.
4. Add the `fmt` and `validate` step through `project_exec`, with the parse-only fallback and the sandbox probes.
5. Teach the planner the infrastructure item (folder in Where, one folder per item, the check line, the index of folders).
6. Wire the shipwright for `.tf` (tool list without a shell, standing instructions, the pack text in its prompt).
7. Fetch the CI plan output (or accept pasted text), extract the counts, compare with the report. Injection fixture for plan text.
8. The dashboard card: report, pack version, plan counts, the words "apply through your own process".
9. Real-model injection run and a dated report; a real-model trial on a throwaway repository with a read-only plan job, written up.

## Open questions

- Is `terraform validate` without provider schemas useful enough to be worth the name, or should the parse-only result be called something else in the interface so no one takes it for a validation?
- Terraform's `fmt` and `validate` need the Terraform binary on the owner's machine. The doctor should check for it, and say which version. Which versions should be supported?
- Should the shipwright be allowed to add a new module call (a `module` block with a new `source`)? A `source` can pull code from anywhere at the next init, which runs in the project's CI with the project's credentials. This design says no. It may be too strict for real use.
- Lock file: a provider bump changes `.terraform.lock.hcl`, a file that decides what code CI downloads and runs. Treated here as a person's file. Is that workable for a team that uses a bot to update providers?
- The plan text and secrets: a plan can show a secret that was put in a variable by mistake. The harness shows counts and addresses only, but the plan stays in the CI log. Out of Quarterdeck's reach, worth a line in the project's own guidance.
- How should a multi-module change that must be applied in order be shown, so a person does not apply them out of order? Probably a simple ordered list in the item; whether to compute it from the module graph is open.
