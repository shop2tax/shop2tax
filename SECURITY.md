# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |

Only the latest release is supported with security updates.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, use the **Security** tab in the GitHub repository to report a vulnerability via GitHub Security Advisories.

### What to Include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 1 week
- **Fix or mitigation**: Depends on severity, typically within 2 weeks for critical issues

### What to Expect

1. You will receive an acknowledgment of your report
2. We will investigate and determine the impact
3. We will develop and test a fix
4. We will release a patch and credit you (unless you prefer anonymity)

## Security Best Practices for Self-Hosting

- Keep your Docker images updated
- Use strong, unique values for all secrets in `.env`
- Never expose port 3002 beyond localhost unless Auth Mode is enabled — in Local Mode there is no login at all
- Enable HTTPS in production (use the provided Caddy configuration)
- Regularly back up your database (`make db-backup`)
- For any deployment reachable by others, enable Auth Mode (Google OAuth) — Local Mode is meant for a single trusted machine
