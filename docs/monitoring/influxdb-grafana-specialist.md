# InfluxDB v3 Core + Grafana Specialist

Deep-dive reference for InfluxDB v3 Core, Grafana dashboard provisioning, and their integration via FlightSQL. Consult when creating Grafana dashboards, writing InfluxDB SQL queries, troubleshooting Telegraf metrics, debugging monitoring stack issues, optimizing time-series queries, or deploying monitoring changes.

Covers the complete monitoring stack: Telegraf → InfluxDB v3 → Grafana.

## Architecture Knowledge

### Data Pipeline

```
Telegraf (host service, NOT container) → InfluxDB v3 Core (Docker :8181) → Grafana (Docker :3000)
```

- Telegraf is a **host-installed service**, not a container
- Telegraf env: `INFLUX_URL="http://localhost:8181"` — must use local HTTP, never external HTTPS
- InfluxDB container: `influxdb` (image: `influxdb:3-core`)
- Database: `system-monitor`
- Common Telegraf inputs: cpu, disk, diskio, docker, mem, net, processes, smart, system, temp

### Remote Server Access (MANDATORY)

**All remote server operations MUST be done via MCP tools. NEVER use SSH commands.**

Remote Server MCP:

- `mcp__remote-server__get_service_logs(service="grafana")` - View Grafana logs
- `mcp__remote-server__get_service_logs(service="influxdb")` - View InfluxDB logs
- `mcp__remote-server__get_service_logs(service="telegraf")` - View Telegraf logs
- `mcp__remote-server__search_service_logs(service="grafana", pattern="influx_flightsql")` - Search logs
- `mcp__remote-server__get_service_status(service="grafana")` - Check service health
- `mcp__remote-server__restart_service(service="grafana")` - Restart a service
- `mcp__remote-server__query_influxdb(query="SELECT ...")` - Query InfluxDB directly
- `mcp__remote-server__query_prometheus(query="up")` - Query Prometheus
- `mcp__remote-server__get_server_health()` - Get overall server health

Disk Health MCP (for disk/SMART diagnostics):

- `mcp__disk-health__list_disks()` - List all storage devices
- `mcp__disk-health__get_disk_health(device="sda")` - Get health report for a specific disk
- `mcp__disk-health__get_smart_attributes(device="sda")` - Get raw SMART attributes
- `mcp__disk-health__get_nvme_health(device="nvme0n1")` - Get NVMe SMART health log
- `mcp__disk-health__get_io_stats()` - Get disk I/O statistics
- `mcp__disk-health__get_raid_status()` - Get mdadm RAID status
- `mcp__disk-health__get_zfs_status()` - Get ZFS pool status
- `mcp__disk-health__get_full_disk_report()` - Comprehensive disk health overview
- `mcp__disk-health__query_influxdb_disk(query="SELECT ...")` - Query InfluxDB for historical disk metrics

**When working with disk-related tasks, prefer the disk-health MCP tools over manual InfluxDB queries.** They handle data source fallbacks (InfluxDB → direct smartctl) and provide formatted reports.

## Grafana + InfluxDB v3 SQL Rules (MANDATORY)

1. **SQL syntax only, NO InfluxQL**
   - ❌ `SELECT time, "field" FROM "measurement"`
   - ✅ `SELECT time, field FROM measurement`
   - Remove ALL double quotes around table names and field names

2. **ALL time_series queries MUST have `ORDER BY time`**
   - Grafana's time series panel requires ascending time order
   - Missing it causes: "unable to process the data because it is not sorted in ascending order by time"

3. **NO `GROUP BY time($__interval)`** — This is InfluxQL
   - Grafana handles time bucketing automatically when `format` is `"time_series"`
   - Causes: "invalid function 'time'. Did you mean 'trim'"

4. **Variable definitions and ALL queries MUST have time constraints**
   - ✅ `SELECT DISTINCT(host) FROM system WHERE time > now() - INTERVAL 24 HOUR`
   - ✅ `SELECT time, field FROM measurement WHERE time > now() - INTERVAL 1 HOUR ORDER BY time`
   - **CRITICAL:** InfluxDB OSS/v3 Core has a **432-file scan limit**. Queries without time ranges will hit this limit and return HTTP 500 errors or incomplete data.
   - When querying historical data, always start with a reasonable time range (e.g., `INTERVAL 24 HOUR` or `INTERVAL 7 DAY`) and expand only if needed.
   - **HTTP 500 errors from InfluxDB are often caused by missing time ranges**, not actual server errors. If a query fails with 500, add or tighten the time constraint.

5. **Multi-value variables use `${variable:sqlstring}`**
   - ❌ `WHERE interface IN ($interface)` — expands as `IN (eno1)` without quotes
   - ✅ `WHERE interface IN (${interface:sqlstring})` — expands as `IN ('eno1')`

6. **NO window functions via FlightSQL**
   - `LAG()`, `LEAD()`, etc. don't work through Grafana's Flight SQL connector
   - For cumulative counters (bytes_recv, read_bytes), use Grafana's `calculateField` transformation with `mode: "rate"`

7. **Series separation: include tag columns in SELECT**
   - ✅ `SELECT time, container_name, usage_percent FROM docker_container_cpu`
   - Grafana creates separate lines per unique tag value

8. **Use `spanNulls: true`** in time series panels for intermittent data

9. **Legend labels show `field_name tag_value` (e.g., `usage_percent deluge`)**
   - InfluxDB v3 SQL + Grafana combines field names with tag values in legend labels
   - The `alias: "$tag_container_name"` approach does NOT work with InfluxDB v3 SQL datasource
   - ✅ Use `renameByRegex` transformation to strip the field name prefix:
     ```json
     "transformations": [
       {
         "id": "renameByRegex",
         "options": {
           "regex": ".*\\s+(.*)",
           "renamePattern": "$1"
         }
       }
     ]
     ```
   - This captures everything after the last space (the container/tag name) and uses it as the label

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `invalid function 'time'` | Using `GROUP BY time($__interval)` | Remove it, Grafana handles bucketing |
| `not sorted in ascending order` | Missing `ORDER BY time` | Add `ORDER BY time` to query |
| `No field named XXX` | Field name mismatch | Check actual schema with MCP logs |
| `432 Parquet files scanned` | Missing time constraint | Add `WHERE time > now() - INTERVAL 24 HOUR` |
| **HTTP 500 from InfluxDB** | Query exceeds 432-file scan limit (missing time range) | Add or tighten `WHERE time > now() - INTERVAL X HOUR/DAY` |
| `context deadline exceeded` | Telegraf can't reach InfluxDB | Check `INFLUX_URL` is `http://localhost:8181` |
| `connection refused` on external URL | Telegraf using HTTPS through proxy | Change to local HTTP URL |

## Grafana Panel Types

- **time_series**: For time-based graphs. Requires `ORDER BY time` in query.
- **table**: For stat panels/gauges showing latest values. Uses `ORDER BY <tag>` and `format: "table"`.
- **gauge**: For static-ish metrics like disk usage. Use `format: "table"` with `reduceOptions.lastNotNull`.
- **stat with graphMode: "area"**: For "card" layouts — one card per tag value, shows a big number + small trend chart below. Use `format: "time_series"` with tag column, `reduceOptions.calcs: ["count"]` or `["lastNotNull"]`.

## Known Telegraf Field Names (verify before querying)

Telegraf plugin field names often differ from documentation or expectations. Always verify by checking InfluxDB logs for schema errors:

| Input Plugin | Measurement | Actual Field Name | Common Mistake |
|-------------|-------------|-------------------|----------------|
| `[[inputs.temp]]` | `temp` | `temp` | ❌ `temp_c` |
| `[[inputs.nvidia_smi]]` | `nvidia_smi` | `temperature_gpu` | ✅ Correct |
| `[[inputs.smart]]` | `smart_attribute` | `raw_value` (for temps where `name='Temperature_Celsius'`) | ❌ `value` |

**Tip:** If a panel shows flat/empty data, search InfluxDB logs with `mcp__remote-server__search_service_logs(service="grafana", pattern="schema error")` to find field name mismatches.

## Sensor-Specific Knowledge

### `[[inputs.temp]]` sensors

| Sensor Tag | Meaning | Notes |
|-----------|---------|-------|
| `coretemp_core_*` | Individual CPU core temperatures | Real per-core readings from Intel MSR |
| `coretemp_package_id_0` | CPU package temperature | Reports hottest core / package-level temp, NOT an average |
| `acpitz` | ACPI Thermal Zone (motherboard) | Often reports stale/constant values on many motherboards — not a bug, the firmware sensor simply doesn't update frequently |
| `nvme_composite` | NVMe SSD temperature from thermal zones | Overlaps with SMART data — prefer the SMART `Temperature_Celsius` measurement instead |
| `pch_*` | Platform Controller Hub (chipset) temperature | Intel chipset sensor |

### `[[inputs.nvidia_smi]]` temperature
- Field: `temperature_gpu` in the main `nvidia_smi` measurement (not a separate measurement)
- Tag: `name` contains GPU name (e.g., `NVIDIA GeForce RTX 4090`)

## Dashboard Layout Best Practices

- **Extract modified dashboards from Grafana UI** → copy the JSON, strip the `id` field, replace the datasource UID with `{{ grafana_influxdb_datasource_uid }}` for the datasource panel, write back to template.
- **Always add `renameByRegex` transformation** to time_series panels with tag values: `"regex": ".*\\s+(.*)", "renamePattern": "$1"` to strip field name prefix from legend labels.
- **Use `spanNulls: false`** in panels where gaps carry meaning (idle disks), `spanNulls: true` for normal continuous metrics.

## Deploy Workflow

```bash
# Deploy Grafana template changes via Ansible
ansible-playbook catafalco.yml --tags grafana --vault-id iac@.vaults

# Restart Grafana via MCP (mandatory after provisioning changes!)
mcp__remote-server__restart_service(service="grafana")

# Deploy Telegraf config changes (edit roles/telegraf/files/telegraf.conf)
# Then restart via MCP:
mcp__remote-server__restart_service(service="telegraf")
```

## Diagnostic Approach

When troubleshooting:

1. **Check service status** first using MCP `get_service_status`
2. **Review logs** using MCP `get_service_logs` for the affected service
3. **Search for specific errors** using MCP `search_service_logs` with relevant patterns
4. **Validate SQL queries** against the rules above (no InfluxQL, has ORDER BY time, has time constraints)
5. **Check Telegraf configuration** if metrics are missing (verify `INFLUX_URL`)

## Proactive Checklist

- Always validate SQL queries against the 9 mandatory rules before suggesting them
- **Include time range constraints in ALL queries** (not just variables) to avoid the 432-file scan limit and HTTP 500 errors
- When a query fails with HTTP 500, the first troubleshooting step should be adding/tightening the time range
- Suggest `spanNulls: true` for panels with intermittent data
- Recommend using MCP tools for all remote diagnostics, never SSH
- **For disk-related tasks, prefer disk-health MCP tools** over manual InfluxDB queries — they handle data source fallbacks and provide formatted reports
- When creating dashboards, ensure proper series separation with tag columns