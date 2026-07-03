"""
Tests for the standalone sim-worker simulation engine.

Covers:
  - parser.py  : ngspice output parsing (tabular and graph modes)
  - error_parser.py : structured error extraction from stderr
  - runner.py  : end-to-end execution (with ngspice mocked)
  - main.py    : FastAPI /simulate and /health endpoints
"""
import json
import textwrap
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# 1. Parser unit tests
# ---------------------------------------------------------------------------

class TestParser:
    """Tests for app.parser.extract_data_from_ngspice_output"""

    def _write_tmp(self, tmp_path, content: str):
        p = tmp_path / "data.txt"
        p.write_text(content)
        return str(p)

    def test_missing_file_returns_error(self, tmp_path):
        from app.parser import extract_data_from_ngspice_output
        result = extract_data_from_ngspice_output(str(tmp_path / "nonexistent.txt"))
        assert "error" in result

    def test_non_graph_output_parsed(self, tmp_path):
        from app.parser import extract_data_from_ngspice_output
        content = "line one\nline two\n"
        path = self._write_tmp(tmp_path, content)
        result = extract_data_from_ngspice_output(path)
        assert result["graph"] == "false"
        assert len(result["data"]) >= 1

    def test_graph_output_detected(self, tmp_path):
        from app.parser import extract_data_from_ngspice_output
        content = (
            "NgSpice 1\n"
            "Title\n"
            "-------\n"
            "Index  time  v(out)\n"
            "0  0.0  1.0\n"
            "1  1e-9  1.1\n"
        )
        path = self._write_tmp(tmp_path, content)
        result = extract_data_from_ngspice_output(path)
        assert result["graph"] == "true"
        assert len(result["data"]) >= 1

    def test_graph_x_values_populated(self, tmp_path):
        from app.parser import extract_data_from_ngspice_output
        content = (
            "NgSpice 1\n"
            "Title\n"
            "-------\n"
            "Index  time  v(out)\n"
            "0  0.0  0.5\n"
            "1  1e-9  0.6\n"
        )
        path = self._write_tmp(tmp_path, content)
        result = extract_data_from_ngspice_output(path)
        assert result["data"][0]["x"][0] == "0.0"


# ---------------------------------------------------------------------------
# 2. Error parser unit tests
# ---------------------------------------------------------------------------

class TestErrorParser:
    """Tests for app.error_parser.parse_ngspice_error"""

    def test_floating_node_detected(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("Error: floating node net1 in circuit")
        assert "floating" in result["summary"].lower()
        assert result["hints"]

    def test_missing_ground_detected(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("no ground node in circuit")
        assert "ground" in result["summary"].lower()

    def test_singular_matrix_detected(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("singular matrix at node x1")
        assert "singular" in result["summary"].lower()

    def test_unknown_subcircuit_detected(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("unknown subcircuit mycomp in line 5")
        assert "mycomp" in result["summary"]

    def test_convergence_detected(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("convergence failed at time step 1e-12")
        assert "converge" in result["summary"].lower()

    def test_generic_error_returns_dict(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error("some completely unknown error message")
        assert "summary" in result
        assert "hints" in result
        assert "codes" in result

    def test_non_string_input_handled(self):
        from app.error_parser import parse_ngspice_error
        result = parse_ngspice_error(12345)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 3. Runner unit tests (ngspice mocked)
# ---------------------------------------------------------------------------

class TestRunner:
    """Tests for app.runner.run_simulation with ngspice mocked."""

    def _make_mock_proc(self, returncode=0, stdout=b"", stderr=b""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.communicate.return_value = (stdout, stderr)
        return proc

    @patch("app.runner.subprocess.Popen")
    def test_successful_run_with_data_file(self, mock_popen, tmp_path):
        from app.runner import run_simulation, _SCRATCH_BASE

        # Build a fake data.txt that would be produced by ngspice
        data_content = (
            "NgSpice\n"
            "Title\n"
            "-------\n"
            "Index  time  v(out)\n"
            "0  0.0  1.0\n"
        )

        proc = self._make_mock_proc()

        def popen_side_effect(*args, **kwargs):
            # Create the data.txt in the work_dir (captured from cwd kwarg)
            cwd = kwargs.get("cwd", "/tmp")
            data_file = f"{cwd}/data.txt"
            with open(data_file, "w") as f:
                f.write(data_content)
            return proc

        mock_popen.side_effect = popen_side_effect

        result = run_simulation("* test netlist\n.end\n")
        assert "fail" not in result

    @patch("app.runner.subprocess.Popen")
    def test_timeout_returns_error(self, mock_popen):
        import subprocess as _subprocess
        from app.runner import run_simulation

        proc = MagicMock()
        proc.communicate.side_effect = _subprocess.TimeoutExpired(cmd="ngspice", timeout=1)
        mock_popen.return_value = proc

        result = run_simulation("* test\n.end\n", execution_timeout=1)
        assert "fail" in result
        assert "timeout" in result["fail"].lower() or result.get("error_help")

    @patch("app.runner.subprocess.Popen", side_effect=FileNotFoundError)
    def test_ngspice_not_found(self, _):
        from app.runner import run_simulation
        result = run_simulation("* test\n.end\n")
        assert "fail" in result
        assert "not found" in result["fail"].lower()


# ---------------------------------------------------------------------------
# 4. FastAPI endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


class TestAPI:
    """Tests for the FastAPI endpoints in app.main."""

    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    @patch("app.main.run_simulation", return_value={
        "graph": "true",
        "data": [{"labels": ["time", "v(out)"], "x": ["0.0"], "y": [["1.0"]]}],
        "total_number_of_tables": 0,
    })
    def test_simulate_success(self, mock_run, client):
        resp = client.post("/simulate", json={
            "netlist": "* test\n.end\n",
            "job_id": "abc-123",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["job_id"] == "abc-123"
        assert body["data"] is not None

    @patch("app.main.run_simulation", return_value={
        "fail": "no ground node",
        "error_help": {"summary": "No ground", "hints": [], "codes": []},
    })
    def test_simulate_failure_returns_200_with_error(self, mock_run, client):
        resp = client.post("/simulate", json={"netlist": "* bad\n.end\n"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "no ground node"

    def test_simulate_empty_netlist_returns_400(self, client):
        resp = client.post("/simulate", json={"netlist": "   "})
        assert resp.status_code == 400
