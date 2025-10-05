#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.10"
# dependencies = ["influxdb_client", "click"]
# ///
import syslog
import subprocess
import time
from datetime import datetime
from pathlib import Path

import click
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS


def get_disk_power_state(device_path: str) -> int:
    """
    Queries the power state of a disk using hdparm -C.
    Returns:
        0 if the drive is active or idle.
        1 if the drive is in standby, sleeping, or state is unknown.
    """
    try:
        result = subprocess.run(
            ["hdparm", "-C", device_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,  # Increased timeout for potentially sleeping drives
        )
        if result.returncode != 0:
            # Log error but treat as unknown/sleeping state
            syslog.syslog(
                syslog.LOG_WARNING,
                f"hdparm error for {device_path}: {result.stderr.strip()}"
            )
            return 1 # Assume sleeping on error

        output = result.stdout.strip()
        # Example output: "/dev/sda:\n drive state is:  active/idle"
        # or              "/dev/sda:\n drive state is:  standby"
        # or              "/dev/sda:\n drive state is:  unknown"
        if "active" in output or "idle" in output:
            return 0 # Active/Idle
        elif "standby" in output or "sleep" in output:
            return 1 # Sleeping
        else: # Includes "unknown" or any unexpected output
            syslog.syslog(
                syslog.LOG_WARNING,
                f"hdparm unknown state for {device_path}: '{output}'"
            )
            return 1 # Treat unknown as sleeping

    except subprocess.TimeoutExpired:
        syslog.syslog(
            syslog.LOG_WARNING,
            f"hdparm timeout for {device_path}"
        )
        return 1 # Assume sleeping on timeout
    except FileNotFoundError:
        syslog.syslog(
            syslog.LOG_ERR,
            f"hdparm command not found. Is 'hdparm' installed?"
        )
        raise # Re-raise to stop script if hdparm is missing
    except Exception as e:
        syslog.syslog(
            syslog.LOG_ERR,
            f"Unexpected error querying {device_path} with hdparm: {e}"
        )
        return 1 # Treat errors as sleeping state


@click.command()
@click.option("-s", "--influx-server", required=True, help="InfluxDB server URL (e.g., http://localhost:8086)")
@click.option("-t", "--influx-token", required=True, help="InfluxDB authentication token")
@click.option("-o", "--influx-org", required=True, help="InfluxDB organization name")
@click.option("-b", "--influx-bucket", required=True, help="InfluxDB bucket name")
@click.argument(
    "disk_paths", # Name for the argument list
    type=click.Path(exists=False, path_type=str), # Path exists check is for files/dirs, not device nodes
    nargs=-1, # Accepts zero or more arguments as a tuple
    required=True, # Require at least one disk path
)
def main(
    influx_server: str,
    influx_token: str,
    influx_org: str,
    influx_bucket: str,
    disk_paths: tuple[str], # Tuple of disk paths provided as arguments
):
    syslog.syslog(syslog.LOG_INFO, f"Starting disk state check for {len(disk_paths)} disks...")

    # Prepare InfluxDB client
    with InfluxDBClient(
        url=influx_server, token=influx_token, org=influx_org
    ) as client:
        write_api = client.write_api(write_options=SYNCHRONOUS)

        current_time_ns = int(datetime.now().timestamp() * 1_000_000_000)

        for disk_path in disk_paths:
            syslog.syslog(syslog.LOG_DEBUG, f"Querying disk: {disk_path}")
            state = get_disk_power_state(disk_path)

            point = (
                Point("disk_state")
                .tag("disk", disk_path) # Use the provided path as the tag
                .field("state", state)
                .time(current_time_ns)
            )
            syslog.syslog(
                syslog.LOG_DEBUG,
                f"Disk {disk_path}: state = {state} at {datetime.fromtimestamp(current_time_ns / 1e9).strftime('%Y-%m-%d %H:%M:%S')}"
            )

            write_api.write(bucket=influx_bucket, record=point)
            # Optional: Add a small delay between queries to avoid overwhelming the controller
            time.sleep(1)

    syslog.syslog(syslog.LOG_INFO, "Disk state check completed.")


if __name__ == "__main__":
    main()