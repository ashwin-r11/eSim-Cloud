"""
Sim-Worker: ngspice runner.

Writes the netlist to disk, spawns ngspice in batch mode, and returns
the parsed result dict.  Designed for use from the main Flask/FastAPI
service layer (main.py) as well as for direct CLI invocation.
"""
import logging
import os
import subprocess
import uuid
from pathlib import Path

from .parser import extract_data_from_ngspice_output
from .error_parser import parse_ngspice_error

logger = logging.getLogger(__name__)

# Directory used for temporary per-simulation scratch space.
# Override via SIM_SCRATCH_DIR env var; defaults to /tmp/esim_simulations.
_SCRATCH_BASE = Path(os.environ.get("SIM_SCRATCH_DIR", "/tmp/esim_simulations"))


def _inject_ngbehavior_ps(netlist: str) -> str:
    """
    Prepend ``set ngbehavior=ps`` inside the .control block so that
    print/wrdata commands use the expected column format.
    """
    lines = netlist.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(".control"):
            lines.insert(i + 1, "set ngbehavior=ps")
            return "\n".join(lines)
    return netlist


def run_simulation(netlist_content: str, execution_timeout: int = 300) -> dict:
    """
    Execute an ngspice simulation for the given netlist text.

    Parameters
    ----------
    netlist_content:
        Raw SPICE netlist as a string.
    execution_timeout:
        Maximum wall-clock seconds to wait for ngspice to finish.
        Raises subprocess.TimeoutExpired (caught and returned as error).

    Returns
    -------
    dict
        On success: the parsed output structure (graph/tabular data).
        On failure: ``{"fail": <stderr>, "error_help": <structured hints>}``
        On exception: ``{"fail": <message>}``
    """
    sim_id = str(uuid.uuid4())
    work_dir = _SCRATCH_BASE / sim_id
    work_dir.mkdir(parents=True, exist_ok=True)

    netlist_path = work_dir / "circuit.cir"
    data_path = work_dir / "data.txt"

    try:
        netlist_content = _inject_ngbehavior_ps(netlist_content)
        netlist_path.write_text(netlist_content, encoding="utf-8")

        logger.info("sim_id=%s  Starting ngspice", sim_id)
        proc = subprocess.Popen(
            ["ngspice", "-ab", str(netlist_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(work_dir),
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=execution_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            logger.error("sim_id=%s  ngspice exceeded timeout (%ds)", sim_id, execution_timeout)
            return {"fail": "execution_timeout", "error_help": parse_ngspice_error("timeout")}

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        logger.info("sim_id=%s  ngspice exited (rc=%d)", sim_id, proc.returncode)

        if data_path.exists():
            result = extract_data_from_ngspice_output(str(data_path))
            if result.get("data"):
                return result
            # data.txt exists but is empty — ngspice probably printed an error
            return {
                "fail": stderr_text or stdout_text,
                "error_help": parse_ngspice_error(stderr_text),
            }
        else:
            combined = stdout_text + stderr_text
            return {
                "fail": combined,
                "error_help": parse_ngspice_error(stderr_text),
            }

    except FileNotFoundError:
        logger.critical("sim_id=%s  ngspice binary not found in PATH", sim_id)
        return {"fail": "ngspice binary not found — is it installed?"}
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("sim_id=%s  Unexpected error", sim_id)
        return {"fail": str(exc)}
    finally:
        # Always clean up scratch directory
        try:
            for item in work_dir.iterdir():
                item.unlink(missing_ok=True)
            work_dir.rmdir()
        except OSError as cleanup_err:
            logger.warning("sim_id=%s  Cleanup failed: %s", sim_id, cleanup_err)
