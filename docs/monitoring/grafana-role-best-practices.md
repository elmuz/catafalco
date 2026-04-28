# Grafana Role Template Best Practices

## Critical Fixes

### 1. Prevent Users from Overriding Provisioned Files

In `roles/grafana/templates/provisioning.dashboards.yml.j2`:
```yaml
allowUiUpdates: false
```
**Reason:** When set to `true`, Grafana overwrites all manually edited provisioning files.

### 2. Fix Container Tag Checks

In `roles/grafana/tasks/main.yml`:

| Dashboard | Current (WRONG) | Correct |
|-----------|-----------------|---------|
| System Monitor | `'influxdb' in containers` | `'system' in containers` |
| Docker Containers | `'influxdb' in containers` | `'prometheus' in containers` |
| S.M.A.R.T. | `'influxdb' in containers` | `'vllm' in containers` |
| Temperature | `'influx Dashboard' in containers` | `'system' in containers` |

**Reason:** Each dashboard should be activated for the container of its target datasource.

### 3. Fix Template Variable Syntax

In all `roles/grafana/templates/*.json.j2` files, the target datasource UID should be:
```json
{
  "datasource": {
    "type": "prometheus",
    "uid": "{{ grafana_prometheus_datasource_uid }}"
  }
}
```
**Do NOT:** use only `"type": "prometheus"` (without a UID)

## Dashboard Template Structure

### vLLM Dashboard (v1 format)
```json
{
  "refresh": "10s",
  "tags": ["vllm", "llm", "speculative-decoding", "inference"],
  "templating": {
    "list": [
      {
        "current": {"selected": false, "text": "prometheus", "value": "<uid>"},
        "type": "datasource",
        "name": "datasource"
      }
    ]
  }
}
```

### Panel Layout (Y positions)
- **Row 1 (y=0):** 6 panels (width 12 each, 0-11, 12-23)
- **Row 2 (y=8):** 6 panels
- **Row 3 (y=16):** Speculative metrics (Acceptance Rate, Speedup)
- **Row 4 (y=24):** System metrics
- **Row 5 (y=32):** Additional metrics
- **Row 6 (y=48):** Advanced metrics

## Deployment Sequence

```bash
# 1. Update the template
# 2. Run Ansible
ansible-playbook catafalco.yml --tags grafana --vault-id iac@.vaults

# 3. Restart Grafana container (mandatory!)
mcp__remote-server__restart_service --service grafana

# 4. Wait for provisioning to update (30 seconds)
# 5. Verify metrics
```

## Troubleshooting

### Problem: Panels show "No Data"

**Cause:** Incorrect Prometheus UID variable
**Fix:** Check that every panel in `roles/grafana/templates/provisioning.dashboards.vllm.json.j2` has the correct `"uid": "{{ grafana_prometheus_datasource_uid }}"`

### Problem: Grafana does not re-read provisioning files

**Cause:** Dashboards do not reload configuration automatically
**Fix:** Restart the Grafana container immediately

### Problem: Errors come from InfluxDB instead of Prometheus

**Cause:** Datasource UID not set correctly or variable substitution failed
**Fix:** Confirm templates use the correct variable name `{{ grafana_prometheus_datasource_uid }}`

## Template Variable Reference

```yaml
# roles/grafana/defaults/main.yml
grafana_prometheus_datasource_uid: PBFA97CFB590B2093
grafana_influxdb_datasource_uid: PA6F3E0496B9A4E62
grafana_vllm_dashboard_uid: "b281712d-8bff-41ef-9f3f-71ad43c05e9b"
grafana_system_dashboard_uid: "system-monitor-dashboard"
grafana_docker_dashboard_uid: "docker-containers-dashboard"
```

## Series Label Format

Use PromQL variables correctly in expressions:
```promql
expr: "sum(rate(vllm:<metric>[5m])) / sum(rate(vllm:counter[5m])) * 100"
legendFormat: "Acceptance Rate (%)"
```

Variable substitutions:
- `$DS_PROMETHEUS` -> `"{{ grafana_prometheus_datasource_uid }}"`
- `$model_name` -> `"{{ grafana_vllm_model_name }}"` (if needed)
- `${DS_PROMETHEUS}` (with braces) - Grafana format

Template variable usage:
- Panel targets should be: `"uid": "{{ grafana_prometheus_datasource_uid }}"`
- Time range variable should be: `$__rate_interval`
- Datasource variable should be: `{{ grafana_prometheus_datasource_uid }}`