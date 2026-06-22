from .SA import optimize_layout
import re
import json
from pathlib import Path
def replace_netlist_params_auto(
    json_path: str,
    original_netlist_path: str,
    output_netlist_path: str = "best_netlist.txt"):
    """
    Automatically identify X<name> devices from the netlist and replace their
    parameters with the corresponding values from the JSON.

    Rules:
    - Instance name XM1 -> look up widths[M1] and lengths[M1] in best_mos_dimensions
    - Instance name XR1 -> look up res_R1 in best_resistors
    - And so on.

    If original_netlist_path does not exist, attempt to read a .txt file from
    ./netlists/ (using the most recently modified one).
    """
    # --- 1. Load optimal parameters ---
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Extract parameter groups
    best_resistors = data.get("best_resistors", {})
    mos_widths = data.get("best_mos_dimensions", {}).get("widths", {})
    mos_lengths = data.get("best_mos_dimensions", {}).get("lengths", {})

    # --- 2. Determine original netlist path ---
    original_path = Path(original_netlist_path)
    if not original_path.exists():
        netlists_dir = Path("netlists")
        if netlists_dir.is_dir():
            # Get all .txt files
            netlist_files = list(netlists_dir.glob("*.txt"))
            if netlist_files:
                # Sort by modification time, use the newest
                latest_file = max(netlist_files, key=lambda f: f.stat().st_mtime)
                print(f"Specified netlist file not found, automatically using latest netlist: {latest_file}")
                original_path = latest_file
            else:
                raise FileNotFoundError(f"Specified netlist file not found, and no .txt netlist files in netlists/ directory")
        else:
            raise FileNotFoundError(f"Specified netlist file not found, and netlists/ directory does not exist")

    # --- 3. Read original netlist ---
    with open(original_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # --- 4. Process each line ---
    new_lines = []
    for line in lines:
        stripped = line.strip()
        # Skip empty lines, comments, and lines starting with . (e.g. .title, .lib)
        if not stripped or stripped.startswith(('.', '*')):
            new_lines.append(line)
            continue

        # Process MOSFETs (lines starting with XM)
        if stripped.startswith('X') and stripped[1].upper() == 'M':
            # Extract MOSFET name (e.g. M1 from XM1)
            mos_name = re.match(r'^X(M\w+)', stripped).group(1)

            # Check if we have corresponding width and length parameters
            if mos_name in mos_widths and mos_name in mos_lengths:
                w_val = mos_widths[mos_name]
                l_val = mos_lengths[mos_name]

                # Replace width parameter
                line = re.sub(r'\bw\s*=\s*[\d\.eE+-]+', f'w={w_val:.6f}', line)
                # Replace length parameter
                line = re.sub(r'\bl\s*=\s*[\d\.eE+-]+', f'l={l_val:.6f}', line)

        # Process resistors (lines starting with RR)
        elif stripped.startswith('RR'):
            # Extract resistor name (e.g. RD1 from RRD1)
            resistor_name = re.match(r'^R(R\w+)', stripped).group(1)
            resistor_key = f"res_{resistor_name}"

            # Check if we have a corresponding resistor parameter
            if resistor_key in best_resistors:
                r_val = best_resistors[resistor_key]
                # Replace resistance value (match number+Ohm pattern)
                line = re.sub(r'(\d+\.?\d*e?[+-]?\d*)Ohm', f'{r_val}Ohm', line)

        new_lines.append(line)

    # --- 5. Save result ---
    output_path = Path(output_netlist_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"Automatic parameter replacement completed, optimal netlist saved to: {output_path.resolve()}")

def  layout_pipline(
        json_path: str,
        original_netlist_path: str,
        output_netlist_path: str = "best_netlist.txt"):
    replace_netlist_params_auto(
    json_path=json_path,
    original_netlist_path=original_netlist_path,
    output_netlist_path=output_netlist_path
)
    optimize_layout(output_netlist_path)
if __name__ == "__main__":
    layout_pipline(
        json_path="./cache/autosizing/best_params.json",
        original_netlist_path="./cache/autosizing/netlist_wo_optim.txt",
        output_netlist_path="./cache/auto_placement/netlist_for_routing.txt"
    )
