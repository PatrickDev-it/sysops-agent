# llama-server binary — bootstrap

`src/config.py` (`_resolve_llama_server_bin`) resolves the binary from portable sources, in order:

1. `SISTEMISTA_LLAMA_SERVER_BIN` — an explicit path (machine-local config belongs in the env,
   never hardcoded in versioned source)
2. `workspace/bin/llama-server[.exe]` — vendored here
3. `llama-server` on `PATH` — the standard reproducible install

The `.exe` is a **thin launcher** (a few KB): it loads its heavy CUDA/ggml DLLs
(`ggml-cuda.dll`, `cublasLt64_12.dll`, `ggml-*.dll`, …) from the **same directory**. So if you
vendor it here, its DLLs must sit beside it — the runtime spawns with `cwd` = the binary's folder
for exactly this reason. Do **not** commit the binary or DLLs (gitignored): they are large,
platform-specific artifacts (~1.2 GB for a CUDA build). Obtain releases from
[ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp), verify the published digest, and
retain its MIT license with any redistribution.

If none of the three resolve, `agent_eval`'s preflight and `ManagedServer._spawn` fail loudly,
naming the path they looked for. Build llama.cpp for your backend, or drop in a release build.
