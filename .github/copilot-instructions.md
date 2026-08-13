## Security Rules

- DO NOT read, access, or relay `.env`, `*.tffiles`, `*.tfvars` or any credentials files under any circumstances.
- If a task implicitly requires environment variables, ask the user to provide them via the terminal, or manual input.

## Code Generation Constraints

- Do not hardcode secrets, environment variables, or connection strings.
- Ensure all recommended external packages are safe from known CVE vulnerabilities.
- Filter out local network IPs and staging/production domain names from error logs.
