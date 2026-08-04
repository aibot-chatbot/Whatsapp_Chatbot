# GitHub Auto-Update

Two mechanisms exist. They solve different problems.

| | Background auto-fetch | Startup launcher |
|---|---|---|
| Script | `scripts/auto-fetch-main.ps1` | `start-with-update.ps1` |
| Runs | Every 15 min + at logon | Only when you launch the app |
| Tracks | `origin/main` always | `origin/<current branch>` |
| Needs clean tree | No | Yes, aborts otherwise |
| Touches your files | Never | Yes, fast-forwards checkout |

## Background auto-fetch (teammate pushes)

A Windows scheduled task, `WhatsappChatbot-GitHubAutoFetch`, runs
`scripts/auto-fetch-main.vbs` every 15 minutes and at logon. The `.vbs` wrapper
exists only to launch PowerShell with a hidden window; running `powershell.exe`
straight from Task Scheduler flashes a console on every run.

Each run fetches `origin`, then fast-forwards the local `main` ref with
`git fetch origin refs/heads/main:refs/heads/main`. Because `main` is not the
checked-out branch, this updates the ref **without checking anything out** — no
working-tree file changes and no risk to uncommitted edits. When the current
branch falls behind, a Windows toast fires once per new remote commit, not once
per run.

Logs and state live outside the repository so the working tree stays clean:

- `%LOCALAPPDATA%\WhatsappChatbotSync\auto-update.log` (rotates at 512 KB)
- `%LOCALAPPDATA%\WhatsappChatbotSync\last-seen.txt` (last-notified commit SHA)

Merging is deliberate. When you are ready to take the team's work:

```powershell
git stash            # only if you have uncommitted edits
git merge main       # local main is already up to date
git stash pop
```

Manage or inspect the task:

```powershell
Get-ScheduledTaskInfo -TaskName 'WhatsappChatbot-GitHubAutoFetch'
Start-ScheduledTask   -TaskName 'WhatsappChatbot-GitHubAutoFetch'   # run now
Disable-ScheduledTask -TaskName 'WhatsappChatbot-GitHubAutoFetch'   # pause
Get-Content "$env:LOCALAPPDATA\WhatsappChatbotSync\auto-update.log" -Tail 20
```

To track a different integration branch, pass `-TrackBranch <name>`.

## Startup launcher

Use the guarded launcher when this checkout should receive new commits from
GitHub before the Flask application starts:

```powershell
Set-Location "C:\Users\Vincent\Desktop\Whatsapp_Chatbot"
.\start-with-update.ps1
```

The launcher fetches the current branch from `origin`, accepts only a
fast-forward update, and starts the application with `.venv\Scripts\python.exe`.

The update stops without changing project files when:

- the working tree has committed or untracked changes;
- the current branch does not have a same-named branch on GitHub; or
- the local and remote histories have diverged.

Generated `.understand-anything` graph files are excluded from the dirty-tree
pre-check because graph metadata normally changes after a commit. Git still
stops the fast-forward if one of those generated files would conflict with a
remote update.

For the first push of a new branch, create its matching GitHub branch and
upstream:

```powershell
git push -u origin <branch-name>
```

To start the system without contacting GitHub:

```powershell
.\start-with-update.ps1 -SkipGitUpdate
```

The application remains on the code loaded at startup. Run the launcher again
to receive later commits and restart the process; it intentionally does not
replace code inside a running production process.

After a pulled commit, Understand-Anything sees the changed Git commit through
the repository's enabled `autoUpdate` configuration and refreshes the graph in
the next Codex session or graph-update workflow.
