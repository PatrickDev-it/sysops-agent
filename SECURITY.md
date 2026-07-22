# Security policy

## Supported versions

Sistemista is an alpha research preview. No released version is currently supported for
production use. Security fixes are applied to `development` first and promoted only after the
repository's validation gates pass.

## Report a vulnerability

Do not disclose exploitable details in a public issue. Use GitHub's **Report a vulnerability**
action in this repository's Security tab to open a private advisory. Include the affected
revision, platform, reproduction steps, impact, and any proposed mitigation.

Maintainers will acknowledge a complete report within five business days. Timelines for a fix
or coordinated disclosure depend on severity and reproducibility; this is not an SLA.

## Threat boundary

Sistemista executes generated commands on the operator's host. The current alpha does not claim:

- process, filesystem, network, or privilege isolation;
- safe unattended operation;
- protection from malicious objectives, model artifacts, shell output, or fetched content;
- complete prevention of sensitive-data disclosure to an enabled remote oracle.

Use a disposable least-privilege VM, review objectives, keep secrets outside the workspace, and
do not expose llama-server ports to untrusted networks. Model files are executable inputs from a
supply-chain perspective; verify their source and digest before use.

The current application policy admits only objectives classified `SAFE`, confines writes to the
run workspace, rejects unresolved dynamic write destinations, and blocks known host-level
mutations. Classifier failures and malformed responses fail closed before planning. These controls
reduce accidental host impact; they are not a sandbox and do not defend against parser bypasses or
a compromised interpreter.

## Credentials

Never commit tokens, private keys, `.env` files, runtime traces, or real infrastructure data.
The repository scans its full public history with Gitleaks. Redaction is defense in depth and
does not replace secret rotation after an exposure.
