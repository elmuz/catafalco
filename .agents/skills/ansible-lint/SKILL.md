---
name: ansible-lint
description: Ansible linting expertise covering ansible-lint commands, rules, and fixes for playbooks, roles, and tasks. Use when linting Ansible code, interpreting errors and warnings, or applying Ansible best practices.
---

# Ansible Lint Expert

Expertise for Ansible linting and best practices: identify and fix issues in Ansible playbooks, roles, and related files.

## Capabilities

- Run `ansible-lint` on playbooks, roles, and tasks
- Interpret and explain linting errors and warnings
- Suggest fixes for common Ansible anti-patterns
- Ensure code follows Ansible best practices
- Help with YAML syntax, Jinja2 templating, and Ansible module usage

## Available Commands

```bash
# Run ansible-lint on the entire project
ansible-lint

# Run on specific files
ansible-lint <file.yml>

# Show rule descriptions
ansible-lint --list-rules

# Show profile (min, basic, moderate, safety, shared, production)
ansible-lint --profile

# List tags for filtering rules
ansible-lint --list-tags

# Skip specific rules
ansible-lint --skip-rule <rule_id>

# Enable specific rules only
ansible-lint --enable-list <rule_id>

# Auto-fix when possible
ansible-lint --fix

# Show detailed error information
ansible-lint --parseable
```

## Common Rules

| Rule ID | Description |
|---------|-------------|
| `name` | All tasks should have a name |
| `fqcn` | Use FQCN (Fully Qualified Collection Name) for modules |
| `no-changed-when` | Commands should register changed_when |
| `no-jinja-when` | No Jinja2 in when clauses |
| `no-tabs` | No tabs in YAML files |
| `trailing-spaces` | No trailing whitespace |
| `risky-file-permissions` | File modules should specify permissions |
| `package-latest` | Package modules should not use state=latest |
| `deprecated-module` | Avoid deprecated modules |
| `syntax-check` | YAML/Ansible syntax validation |
| `var-naming` | Variables should follow naming conventions |
| `role-name` | Role names should follow conventions |

## Best Practices

1. **Always name tasks** - Every task should have a descriptive `name:` field
2. **Use FQCN** - Use `ansible.builtin.copy` instead of just `copy`
3. **Avoid `changed_when: false`** - Only when truly idempotent
4. **Use `block/rescue`** - For error handling in complex tasks
5. **Quote Jinja2** - Always quote variables: `"{{ var }}"`
6. **Use `vars_files`** - For organizing variables
7. **Avoid `sudo`** - Use `become:` instead
8. **Use handlers** - For service restarts on config changes
9. **Tag tasks** - For selective execution
10. **Document roles** - Include README.md in each role

## Workflow

1. Run `ansible-lint` to identify issues
2. Categorize issues by severity (error vs warning)
3. Fix critical errors first (syntax, undefined variables)
4. Address best practice violations
5. Re-run to verify fixes

## Project-Specific Configuration

This project uses `.ansible-lint` for custom linting configuration. Check this file for:
- Skipped rules
- Custom rule configurations
- Profile settings
- Exclude patterns

## When to Use

- Before committing changes
- When adding new roles or playbooks
- When troubleshooting playbook failures
- When learning Ansible best practices