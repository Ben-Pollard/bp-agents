# Architectural Principles

- **Adopt, don't build.** Prefer existing platforms (Plane, Langfuse, LangGraph) over custom solutions. Only build what bridges them.
- **The graph is the test surface.** Tests invoke `graph.invoke()`, not internal functions. Nodes take dependencies via `Runtime[Context]`.
- **Module boundaries are seams.** Only create ports when there are (or will be) multiple adapters. One adapter = no port.
- **Skills keep their git-availability check.** Skills work identically in and out of the orchestrator; git is simply absent in the sandbox.
- **Ephemeral sandboxes, persistent workspace.** Containers are per-dispatch; the workspace survives on the host across stages.
- **Env-first configuration.** Secrets and settings flow through environment variables. No custom config file format in V1.