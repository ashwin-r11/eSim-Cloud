"""
Sim-Worker: ngspice error parser.

Translates raw ngspice stderr into structured, user-friendly hints.
Mirrors esim-cloud-backend/simulationAPI/helpers/error_parser.py
but runs standalone (no Django dependency).
"""
import re


def parse_ngspice_error(stderr_text: str) -> dict:
    """
    Parse ngspice stderr and return a dict with:
        - summary (str)  – one-line description of the problem
        - hints  (list)  – actionable suggestions for the user
        - codes  (list)  – extracted error keywords / lines
    """
    if not isinstance(stderr_text, str):
        stderr_text = str(stderr_text)

    lower = stderr_text.lower()

    # Collect notable lines for 'codes'
    important_lines = re.findall(
        r"(?i)(?:error:|note:|could not find|can't find model).*", stderr_text
    )
    codes = [l.strip() for l in important_lines]

    if "floating node" in lower or "node is floating" in lower:
        m = re.search(
            r"(?:floating node|node is floating)\s+(\S+)", stderr_text, re.IGNORECASE
        )
        node = m.group(1) if m else "unknown"
        return {
            "summary": f"Node '{node}' is floating (not connected to any component).",
            "hints": [
                "Connect all component pins to a wire.",
                "Ensure every node has a DC path to ground.",
            ],
            "codes": codes + ["floating node"],
        }

    if "unknown subcircuit" in lower or "could not find subcircuit" in lower:
        m = re.search(
            r"(?:unknown subcircuit|could not find subcircuit)\s+(\S+)",
            stderr_text,
            re.IGNORECASE,
        )
        name = m.group(1) if m else "unknown"
        return {
            "summary": f"Subcircuit '{name}' could not be found.",
            "hints": [
                "Verify the .subckt definition is included in the netlist.",
                "Check for spelling mistakes in the component name.",
            ],
            "codes": codes + ["unknown subcircuit"],
        }

    if any(
        k in lower
        for k in ("no ground node", "node 0 is not defined", "no dc path to ground", "missing ground")
    ):
        return {
            "summary": "The circuit has no ground connection.",
            "hints": ["Add at least one GND symbol connected to the circuit."],
            "codes": codes + ["missing ground"],
        }

    if any(k in lower for k in ("singular matrix", "matrix is singular", "matrix singular")):
        return {
            "summary": "The circuit matrix is singular (mathematical inconsistency).",
            "hints": [
                "Check for voltage sources in a loop without series resistance.",
                "Ensure there are no disconnected nodes.",
            ],
            "codes": codes + ["singular matrix"],
        }

    if "convergence" in lower or "time step" in lower:
        return {
            "summary": "Simulation failed to converge.",
            "hints": [
                "Add a small series resistor (e.g. 1 mΩ) to inductive elements.",
                "Reduce the time step in the .tran command.",
                "Check initial conditions.",
            ],
            "codes": codes + ["convergence"],
        }

    if "can't find model" in lower or "no model" in lower:
        m = re.search(r"(?:can't find model|no model)\s+(\S+)", stderr_text, re.IGNORECASE)
        model = m.group(1) if m else "unknown"
        return {
            "summary": f"Model '{model}' not found.",
            "hints": [
                "Include the correct .model or .lib statement in the netlist.",
                "Verify the model file path if using .include.",
            ],
            "codes": codes + [f"can't find model {model}"],
        }

    # Fallback
    first_error = important_lines[0].strip() if important_lines else "See full output for details."
    return {
        "summary": "ngspice reported an error.",
        "hints": ["Review the full error output.", first_error],
        "codes": codes,
    }
