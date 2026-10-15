# Optional setup for future coding sessions

This session could edit project files and execute local tools, but could not
download packages or stage Git files. These are execution permissions, not a
missing authorization in the task prompt. Nothing in this repository changes
the client's managed permission policy.

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

If policy cannot change, the practical alternative is to install the README's
development dependencies in your own terminal before the next session, let the
agent work/test in the project, then stage and commit the reviewed files yourself:

```powershell
git add .gitignore AGENTS.md LICENSE README.md pyproject.toml configs docs src tests tools samples/README.md
git diff --cached --stat
git commit -m "feat: add local HUD OCR and acquisition feasibility probes"
```

The explicit paths keep the review focused; still inspect the staged content.
Never force-add the ignored screenshots or artifacts. No push is needed.
