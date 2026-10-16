# Optional setup for future coding sessions

This session could edit project files and execute local tools, but could not
download packages or stage Git files. These are execution permissions, not a
missing authorization in the task prompt. Nothing in this repository changes
the client's managed permission policy.

The live-capture milestone confirmed the distinction: agent commands failed DNS
resolution for `gql.twitch.tv`, and a connection to the local test server failed
with Windows socket error 10013. The same capture scripts succeeded from the
user's normal PowerShell terminal. The blocker was the agent execution sandbox,
not Twitch credentials, streamer setup or a different implementation.

This session also disables sandbox approval prompts, so the agent cannot request
a one-command network escalation. Before the next session, review the client's
active permissions and allow command networking plus interactive approvals for
actions outside its sandbox when appropriate. Keep project writes scoped to this
workspace. In CLI/IDE contexts, the following documented configuration is the
usual starting point; app/managed profiles may require their own controls.

For a local Codex CLI/IDE session that allows interactive approvals, official
[OpenAI permission guidance](https://learn.chatgpt.com/docs/agent-approvals-security)
documents workspace-write plus on-request approval and optional network access:

```toml
# User-level Codex configuration, if supported by your client and policy.
sandbox_mode = "workspace-write"
approval_policy = "on-request"

[sandbox_workspace_write]
network_access = true
```

Do not apply these settings blindly to a managed ChatGPT Work/local-access
profile: its controls may be configured elsewhere, and managed requirements take
precedence. Review the active permission settings in your client. Keep writes
limited to this project; allow dependency downloads only when needed. Protected
`.git` writes may still require an allowed approval mechanism. Full machine
access is not necessary for this prototype.

If a network proxy/allowlist is enabled, allow the selected Twitch/CDN hosts and
package hosts, plus the exact loopback address `127.0.0.1` for the HLS fixture.
Enabling command networking and permitting loopback destinations are separate
controls in those profiles. Git metadata remains a protected path under
workspace-write. A fresh session is the appropriate place to verify changed
settings; do not change permissions mid-benchmark. A successful package-index
request and localhost HLS capture can establish that agent execution is ready.

If policy cannot change, the practical alternative is to install the README's
development dependencies in your own terminal before the next session, let the
agent work/test in the project, then stage and commit the reviewed files yourself:

```powershell
git add .gitignore AGENTS.md LICENSE README.md pyproject.toml configs docs src tests tools samples/README.md
git diff --cached --stat
git commit -m "feat: add remote frame capture and OCR benchmarks"
```

The explicit paths keep the review focused; still inspect the staged content.
Never force-add the ignored screenshots or artifacts. No push is needed.
