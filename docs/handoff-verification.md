# Fresh agent handoff verification

The local folder handoff passed six fresh-context agent trials using the current guide across three cases. Each case ran twice. Four comparison trials using the earlier guide also passed. No publisher onboarding blocker was reproduced, so no per-mod code, registration, or runtime workaround was added.

This check ran on November 12, 2026 against commit `5e073d9fd5db860fa7218b680416fa8c6d994bf0`. The comparison used the earlier documentation at `bc6e400bd4a367fee1579bc58fb1b71365daff66`. The publishing code was the same in both versions. Agents started without this chat's history and received a publisher checkout, a disposable mod, the preparation task, and a publication hold.

## Cases and results

| Case | Current guide | Earlier guide |
| --- | --- | --- |
| Zomboid Workshop root with item metadata and a path containing spaces | 2 of 2 passed | 2 of 2 passed |
| Another game's plain content folder with explicit IDs and unavailable desktop Steam | 2 of 2 passed | 2 of 2 passed |
| Held-out Zomboid `Contents` folder with explicit IDs and ready desktop Steam | 2 of 2 passed | Not run |

Every trial supplied `WORKSHOP_BACKEND=steamcmd` in the task environment. Every future update command explicitly selected `--backend desktop`, preserving the requested no-relogin behavior despite that inherited setting. All current-guide agents read both `AGENTS.md` and the quickstart. The equal comparison results support no claim that the new guide is better or faster than the earlier one.

## What was exercised

Each agent ran the actual folder validation command, obtained the correct application and item mapping, probed session readiness, and wrote a handoff with a content path, working directory, and future update command. The runtime cache started empty. The real pinned Steamworks dependency installer provisioned it automatically. No GitHub access, per-mod configuration file, service, compiler, or publisher modification was needed.

For unavailable Steam, agents reported the prerequisite and preserved the publication hold. They did not select another login path. Original publisher and mod files retained their initial hashes, and no `workshop-publisher.json` registration appeared.

The lead and an independent reviewer checked the actual command transcripts and all ten handoff artifacts. The lead parsed each proposed future command, checked its executable, working directory, exact ID arguments, and reported content path, and reran its validation form without `--publish`. Both supported Zomboid forms worked: a Workshop root with metadata, or its `Contents` directory with explicit IDs.

## Publication boundary and limits

The agent trials used Steam readiness fixtures at the native-service boundary. Trial copies rejected upload and separate-login transport calls before those calls could reach Steam. The recorded task commands contain no upload invocation, and the transport audits contain only the expected probes. A separate probe through the unmodified publisher also reported that the real local desktop Steam session was online and ready. That probe requested no item update or new login.

These observations establish the tested preparation workflows, not a live upload, item ownership, Workshop permission, or universal reliability across agents, games, and operating systems. The fresh-agent trials used a Linux host and GPT agents; exact model identifiers and token usage were not exposed. GitHub release and cloud onboarding were outside these agent trials. Existing cross-platform CLI and native API tests cover a different scope.

The host agents had fresh conversation contexts and disposable files, but their tools were not OS-confined. Task commands used private homes and recorded environment launchers. The command records and patched transport audits do not constitute an exhaustive host security audit. The automated checker also has narrower coverage than the independent artifact review and read-only command revalidation.

## Check qualification and retained evidence

Before agent runs, known-good reference handoffs passed and a deliberately unsafe SteamCMD future command failed. Initial qualification exposed a test-fixture directory permission error; the fixture was corrected to represent a writable checkout before agent execution.

After agents returned, the first checker rejected a valid `Contents` command because it required the Workshop-root path spelling. The checker was corrected to accept both documented forms, and qualification then accepted both while still rejecting the unsafe backend. Original artifacts and the scoring correction remain in the evidence. No publisher change was made to satisfy an incorrect check.

Evidence is retained outside Git beneath `${XDG_STATE_HOME:-$HOME/.local/state}/app-verification/steam-workshop-publisher/handoff-20261112-201626/`. `plan.json` and `holdout.json` record the conditions and acceptance criteria. `run-01` and `run-02` contain per-run handoffs, verbatim final reports, command outputs, transport audits, source hashes, and scored results. `postflight.json` records the independent command revalidation; `live-probe.json` records the separate real readiness probe. The qualification records and `scoring-correction.json` preserve the test repairs.

The agent trials are local, on-demand verification. They add no recurring automation or agent jobs to GitHub Actions.
