# Security and responsible use

This utility can overwrite physical card data and change reader settings. Use it
only on authorized hardware. It is not a secure payment, access-control or
credential-verification system. A UID is not proof of identity.

## Reporting

Do not post exploitable vulnerability details, keys or private card dumps in
public issues. Use GitHub's **Security > Report a vulnerability** for this
repository when available. If the private reporting action is unavailable, open
an issue requesting a private contact channel without disclosing the vulnerability.
There is no promised response SLA for this community project.

## Scope and limits

- This first preview is the only maintained release line. Use the latest release.
- The desktop app has no network API or listening server. The manual is local;
  external documentation opens only on user request.
- Keys entered in Memory stay in application memory; supported key-load commands
  are redacted in the log. Other raw commands and responses may contain secrets.
- Raw APDUs and protected-write overrides are expert features, not a security sandbox.
- Demo operations never connect to PC/SC. Automated release checks use Demo only.
- Windows binaries are unsigned. Verify their source and SHA-256 checksum; follow
  your organization's software policy. Never disable antivirus to run this tool.
- If a transport error occurs during a write, its outcome can be unknown. Inspect
  the card before repeating any mutation, particularly a value increment/decrement.