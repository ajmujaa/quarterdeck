# Setup, step by step

This page takes you from nothing installed to a project attached, a pull request reviewed by the crew, and your first decision records. Each step says what you should see when it worked and what to do when it did not. Nothing here writes to a project of yours until a step says so.

Time: about 20 minutes, plus the sign-ins you may not have done yet.

## 1. What you need

| Tool | Why | Check |
| --- | --- | --- |
| macOS or Linux | macOS is the tested system. Linux is run in CI only. | |
| Python 3.10 or newer | Quarterdeck itself | `python3 --version` |
| git | Reads your projects | `git --version` |
| bash and jq | The duties are bash scripts | `jq --version` |
| GitHub CLI (`gh`), signed in | Reads and posts to pull requests | `gh auth status` |
| Claude Code (`claude`), signed in | Every model call runs through it, as you | `claude --version` |
| Node 20 or newer | Only for the npm install and the page-logic tests | `node --version` |
| bubblewrap (Linux only) | The sandbox for project commands. Without it they are refused. | `bwrap --version` |

Install the missing ones:

```bash
# macOS
brew install jq gh

# Debian or Ubuntu (run the update first, or a fresh image answers 404)
sudo apt-get update && sudo apt-get install -y jq bubblewrap
```

Claude Code: https://claude.com/claude-code

Quarterdeck has no login of its own. Every model call uses the `claude` command that is already on your machine, with your account and your usage limits. Read the provider's terms for automated use before you schedule many runs.

## 2. Sign in to the two tools

```bash
claude        # run it once, sign in with your Claude account or an API key, then exit
gh auth login # choose GitHub.com, HTTPS, and sign in through the browser
```

You should see: `gh auth status` says you are logged in, and `claude` opens without asking you to sign in again.

## 3. Install Quarterdeck

Pick one.

```bash
brew tap ajmujaa/quarterdeck && brew install qtdeck     # macOS
npm install -g qtdeck                                   # needs Node 20+ and Python 3.10+
```

Or from source, with no installer and nothing placed outside the folder:

```bash
git clone https://github.com/ajmujaa/quarterdeck.git
cd quarterdeck
export PATH="$PWD/bin:$PATH"      # add this line to your shell profile to keep it
```

You should see: `qtdeck help` prints a list of commands.

## 4. Check the machine

```bash
qtdeck setup     # checks the tools and prints the install command for anything missing; installs nothing
qtdeck doctor    # a quick wiring check: tools, sign-ins, data folder, dashboard, sandbox
```

`doctor` names each problem in plain words and ends with `all good` or `N problems: ...`. Fix what it names and run it again.

Your data (registry, runs, drafts, config) lives in `~/.quarterdeck`, apart from the program. `qtdeck home` shows where. Set `QUARTERDECK_HOME` to put it elsewhere.

## 5. Open the dashboard

```bash
qtdeck dashboard
```

This opens a one-time pairing link to `http://127.0.0.1:7878` in your browser. The server listens on your own machine only.

- The link works once and is good for five minutes. A tab opened without it says how to get a new one: `qtdeck dashboard link` prints a fresh link, for example to pair a second browser.
- The first-run screen lists what this machine has and lacks, the same as `doctor`, with a Copy button on each fix.
- **Look around in Demo** fills the dashboard with invented data. Use it to see every page before you connect anything.
- To stop it: `qtdeck dashboard stop`. Keep the terminal or the process running while you use it.

## 6. Attach your first project

Attaching is onboarding. It reads the folder, says what it found, and registers the project only when you say so.

In the dashboard: **Add a project**, paste a folder path such as `~/Projects/my-app`, press **Scan**. Or from a terminal:

```bash
qtdeck attach ~/Projects/my-app            # shows what it found and proposes a set-up; changes nothing
qtdeck attach ~/Projects/my-app --apply    # registers it
```

What it does, in order:

1. **Survey, no model.** It reads the layout, languages, scripts, dependencies, which documents exist and the state of git, from files alone. It never opens secret files and never changes the project.
2. **Missing docs.** If there is no README or architecture overview it says so. `qtdeck docs my-app` has the scribe draft them; you read the draft, and only your yes puts it on a new branch.
3. **Decision records.** It reports whether `docs/decisions` has records. Step 9 covers what to do when it has none.
4. **The crew.** It proposes which duties to turn on, with a reason for each. Duties that also fit your stack are listed and stay off until you switch them on.
5. **The checklist.** `qtdeck ready my-app` shows the scan, the verify command, the GitHub repo, the docs, the agents, cycles and decisions, and ends with one next action.

The verify command is the one command that proves a change works (for example `npm test` or `pytest`). If none was found, set it with `qtdeck attach ~/Projects/my-app --apply --verify "<command>"`. Prove it once with `qtdeck ready my-app --prove`. It runs in the sandbox on a throwaway copy of your default branch.

Project folders must be under your home folder and not hidden. To allow another place, set `QUARTERDECK_PROJECT_ROOTS` in your config file (step 11).

A project with no GitHub repo still works: tickets are kept locally and `qtdeck repo my-app` lists the ways to get a repo.

## 7. Have the crew review a pull request

Start by hand so you can see what it does. Nothing is posted without `--apply`.

```bash
qtdeck run my-app surveyor --pr 12           # reports only: prints the review it would post
qtdeck run my-app surveyor --pr 12 --apply   # posts it as a comment on the pull request
```

The model only reads. The script posts the comment. Merging stays yours; no agent ever merges.

## 8. Review every new pull request, automatically

1. Run the surveyor with no `--pr` to sweep all open pull requests once:

   ```bash
   qtdeck run my-app surveyor            # reports only
   qtdeck run my-app surveyor --apply    # posts the reviews
   ```

   It reviews each pull request once per commit, newest activity first, at most 5 new reviews per run (`QUARTERDECK_MAX_ITEMS`). It skips drafts and bots.

2. Know whose pull requests it reads. By default only the repository's owner, members and collaborators. Pull requests from strangers on a public repo are skipped, because their text goes to the model and costs money. To review everyone's, set `QUARTERDECK_REVIEW_AUTHORS="all"` in your config file, and set a daily spend limit first (step 10).

3. Make it run on a timer: in the dashboard open **Projects, Operations**, press **New schedule**, choose your project and the `surveyor` duty, set **every** to `10m`, and tick **Apply**. A schedule never starts new work once the day's spend limit is reached.

Other reviewers you can run on a pull request the same way: `marshal` (security), `joiner` (interface), `inspector` (does it do what it claims), `quartermaster` (dependencies). `qtdeck duties` lists them all.

## 9. Start a project with decisions

Agents work better when the important choices are written down. Quarterdeck keeps them as short records in your own repository, `docs/decisions/NNNN-title.md`. Every later review is shown the records whose paths or keywords match what it touches, and the builder is shown the ones that match its ticket.

When a project has no records, the Decisions line of its checklist says so. Then:

1. **Ask for suggestions.** In the dashboard, open the project, open the Decisions line and press **Suggest decisions**. Or:

   ```bash
   qtdeck run my-app logkeeper --suggest
   ```

   A read-only agent lists 3 to 6 choices the code already makes. Each is tied to real files; a suggestion that points at a file that is not there is dropped. Nothing is written to your project. The list is kept in your data folder. It costs a few cents.

2. **Give the reason.** The code shows what was chosen, not why. Each suggestion asks the one question only you can answer. The agent never invents the reason.

3. **Record the ones you want.** In the dashboard write your reason in the box and press **Record this**. Or:

   ```bash
   qtdeck run my-app logkeeper --pick 2 --why "Keys are regulated, we never hold them." --apply
   ```

   This opens a pull request that adds one file. Read it, edit it if the wording is off, and merge it yourself.

   Without `--apply` it only prints the record it would propose.

4. **Tell your own agents to follow them.** Add a line to `AGENTS.md` or `CLAUDE.md` saying to follow `docs/decisions/`.

You can also write a decision in your own words and record it: `qtdeck run my-app logkeeper --text notes.txt --apply`, or from a decision panel's ruling with `--panel <id>`.

## 10. Set your spend limits

In the dashboard open **Settings, Spend limits**. Three amounts in dollars:

| Limit | Default | Meaning |
| --- | --- | --- |
| Per call | $6 | One model call is stopped at this amount. |
| Per cycle | $15 | One whole cycle (ticket to branch) stops here. |
| Per day, automatic work | $120 | Queued and scheduled work starts nothing new once today's spend reaches this. A run you start by hand is not stopped by it. |

The per-call limit cannot be more than the per-cycle limit. An empty box goes back to the default. A value above the default is marked. The limits are saved to `config/quarterdeck.env` in your data folder.

Who pays: by default your Claude plan. `qtdeck billing` shows each duty's setting, and `qtdeck keys set anthropic` stores an API key if you would rather bill one. The API key has its own daily cap, in the same card. `qtdeck spend` shows where the money went.

## 11. Your config file

Settings that have no dashboard control go in `~/.quarterdeck/config/quarterdeck.env`. The program ships its own defaults; your file is read after them and wins. Use plain lines:

```bash
QUARTERDECK_REVIEW_AUTHORS="all"
QUARTERDECK_MAX_ITEMS="3"
QUARTERDECK_PROJECT_ROOTS="/Users/you/Projects:/Volumes/work"
```

## 12. Say what you want built

```bash
qtdeck ticket new my-app "a page with a counter and a reset button"   # drafts one to five tickets; files nothing
qtdeck ticket new my-app "..." --apply                                # files them (GitHub issues, or local tickets with no repo)
qtdeck cycle my-app --issue 12                                        # one issue through the whole crew, then stops for you
```

A cycle needs to be allowed first: `qtdeck enable my-app cycle`. It spends model money, so it is never on by default. A cycle ends at a branch or pull request for you to read. It never merges.

## Every day

| I want to | Do this |
| --- | --- |
| See what is registered and what ran | `qtdeck status`, `qtdeck runs 20` |
| Read a log | `qtdeck logs surveyor-my-app` |
| Pair another browser | `qtdeck dashboard link` |
| Sign every browser out | `qtdeck dashboard sessions revoke` |
| Turn an agent on or off | `qtdeck enable my-app joiner`, `qtdeck disable my-app joiner` |
| Update | `brew upgrade qtdeck`, `npm update -g qtdeck`, or `git pull` in the clone. Then `qtdeck dashboard stop` and start it again. |

## When something is wrong

| You see | Cause and fix |
| --- | --- |
| `doctor` lists a missing tool | Run the command it prints, then `doctor` again. |
| The page says it is not paired | Run `qtdeck dashboard link` and open the new link within five minutes. |
| "Today's budget is spent" | The per-day limit is reached. Raise it in Settings, Spend limits, or wait until tomorrow. Hand-started runs still work. |
| A project command is refused on Linux | Install `bubblewrap`. Without a sandbox, project commands do not run. |
| "no suggestions yet" when you pick | Run `--suggest` first. |
| The surveyor reviewed nothing | It reviews each pull request once per commit and skips drafts, bots and (by default) strangers. `qtdeck runs 5` shows its verdict. |
| A usage-limit message | Your Claude plan is at its limit. The run stopped and wrote nothing. Try later. |

## What it will never do

It never merges a pull request, never pushes to your default branch, never touches `.env` files or anything that holds a secret, and never writes to a project without your `--apply` or a click. Read [SECURITY.md](SECURITY.md) before you trust it with anything you care about.

The rest is in the [guide](GUIDE.md).
