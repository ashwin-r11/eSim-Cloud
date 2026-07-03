"""
Sim-Worker: Standalone ngspice simulation worker.

Parses a raw ngspice output (data.txt) into a JSON structure
compatible with the eSim-Cloud frontend plotter.
"""
import re
import os


def extract_data_from_ngspice_output(path_to_file: str) -> dict:
    """
    Parse the data.txt file produced by ngspice -ab and return a
    JSON-serialisable dict with the following shape:

        {
            "graph": "true" | "false",
            "data": [
                {
                    "labels": ["time", "v(out)", ...],
                    "x": ["0.0", "1e-09", ...],
                    "y": [["0.0", ...], ...]
                },
                ...
            ],
            "total_number_of_tables": <int>   # only present for graph=true
        }

    Returns {"error": <message>} if parsing fails.
    """
    try:
        if not os.path.exists(path_to_file):
            return {"error": f"Output file not found: {path_to_file}"}

        with open(path_to_file, "r") as f:
            f_contents = f.readlines()

        graph = False
        if len(f_contents) > 3 and "---" in f_contents[2]:
            graph = True

        if not graph:
            json_data: dict = {"data": [], "graph": "false"}
            for line in f_contents:
                parts = line.split()
                if parts:
                    json_data["data"].append(parts)
            return json_data

        # --- Tabular / graph output ---
        json_data = {"data": [], "graph": "true"}
        current_headers: list = []
        total_number_of_tables = 0

        for line in f_contents:
            parts = line.split()
            if not parts:
                continue

            if "Index" in parts:
                if parts != current_headers:
                    current_headers = parts
                    json_data["data"].append({"labels": [], "x": [], "y": []})
                    idx = len(json_data["data"]) - 1
                    for _ in range(2, len(current_headers)):
                        json_data["data"][idx]["y"].append([])
                    for x in range(1, len(current_headers)):
                        json_data["data"][idx]["labels"].append(current_headers[x])
                        total_number_of_tables += 1
            else:
                if re.match(r"[0-9]+", line):
                    idx = len(json_data["data"]) - 1
                    data = json_data["data"][idx]
                    data["x"].append(parts[1])
                    for x in range(len(data["y"])):
                        if len(parts) > x + 2:
                            data["y"][x].append(parts[x + 2])

        json_data["total_number_of_tables"] = (
            total_number_of_tables - len(json_data["data"])
        )
        return json_data

    except Exception as exc:  # pylint: disable=broad-except
        return {"error": str(exc)}
