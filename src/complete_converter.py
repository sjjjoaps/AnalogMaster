import os
import matplotlib.pyplot as plt
from collections import defaultdict
import sys
import re
from matplotlib.transforms import Affine2D
import matplotlib.patches as patches
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from .netlist_to_routing_converter import NetlistParser, PlacementParser, RoutingGridGenerator, RoutingFormatGenerator
import AStarSearchSolver as solver

class NetlistToRoutingConverter:
    """Complete netlist conversion and routing tool"""

    def __init__(self, tile_size=1):
        self.netlist_parser = NetlistParser()
        self.placement_parser = PlacementParser()
        self.grid_generator = RoutingGridGenerator(tile_size)
        self.format_generator = RoutingFormatGenerator(self.grid_generator)

    def convert_and_route(self, netlist_file, placement_file, output_dir):
        """Complete netlist-to-routing conversion pipeline"""
        print("🚀 Starting netlist-to-routing full pipeline...")

        # Create output directories
        os.makedirs(output_dir, exist_ok=True)
        gr_file = os.path.join(output_dir, "converted_netlist.gr")
        solution_dir = os.path.join(output_dir, "solution")
        os.makedirs(solution_dir, exist_ok=True)
        results_dir = os.path.join(output_dir, "results")
        os.makedirs(results_dir, exist_ok=True)

        try:
            # Step 1: Parse netlist
            print("📄 Step 1: Parsing SPICE netlist...")
            netlist_data = self.netlist_parser.parse_netlist(netlist_file)

            # Extract all nets
            all_nets = self._extract_all_nets(netlist_data['devices'])

            print(f"   Found {len(netlist_data['devices'])} devices")
            print(f"   Identified {len(all_nets)} connected nets")
            print(f"   All nets: {all_nets}")
            # Step 2: Parse device placement
            print("📍 Step 2: Parsing device placement...")
            device_pins = self.placement_parser.parse_placement(placement_file)
            print(f"   Parsed pin coordinates for {len(device_pins)} devices")
            print(f"   All pins: {device_pins}")

            # Step 3: Build net-to-pin mapping
            print("🗂️ Step 3: Building net-to-pin mapping...")
            net_to_pins, offset_x, offset_y = self.grid_generator.build_net_to_pins(
                netlist_data['devices'],
                device_pins,
            )

            # Step 4: Generate routing nets
            print("📌 Step 4: Generating routing net data...")
            routing_nets = self.grid_generator.generate_routing_nets(net_to_pins)
            print(f"   Generated {len(routing_nets)} routing nets")

            # Check if any routing nets exist
            if not routing_nets:
                print("⚠️ Warning: No routing nets generated, skipping routing, plotting layout only")

                # Plot layout directly
                self.visualize_placement_and_routing(
                    net_to_pins=net_to_pins,
                    solution_file=None,
                    device_contours_file="./cache/auto_placement/placement_full.txt",
                    offset_x=offset_x,
                    offset_y=offset_y,
                    tile_size=self.grid_generator.tile_size,
                    save_dir=results_dir
                )

                # Generate result report
                self._generate_report(netlist_data, all_nets, device_pins, routing_nets, output_dir)

                print("✅ Layout plotting completed!")
                print(f"📁 Results saved in: {output_dir}")
                return True

            # Step 5: Generate .gr file
            print("📝 Step 5: Generating A* algorithm input file...")
            self.format_generator.generate_gr_file(routing_nets, gr_file)
            print(f"   Generated file: {gr_file}")

            # Step 6: Execute A* routing algorithm
            print("⚡ Step 6: Executing A* routing algorithm...")
            route_caps = solver.solve(gr_file, solution_dir)

            self.visualize_placement_and_routing(
                net_to_pins=net_to_pins,
                solution_file=os.path.join(solution_dir, "converted_netlist_Astar_solution.txt"),
                device_contours_file="./cache/auto_placement/placement_full.txt",
                offset_x=offset_x,
                offset_y=offset_y,
                tile_size=self.grid_generator.tile_size,
                save_dir=results_dir
            )

            # Generate result report
            self._generate_report(netlist_data, all_nets, device_pins, routing_nets, output_dir)

            print("✅ Conversion and routing completed!")
            print(f"📁 Results saved in: {output_dir}")

            return True
        except Exception as e:
            print(f"❌ Conversion error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _handle_mos_substrate_connections(self, devices):
        """Handle default MOS substrate (B) connections: NMOS→GND, PMOS→VDD"""
        # Define GND-equivalent node set
        gnd_equivalents = {'GND', '0', 'VSS', 'circuit.gnd'}

        for device_name, device_info in devices.items():
            # Only process MOS devices
            if not device_name.startswith('XM'):
                continue

            model = device_info['type'].lower()
            pin_to_net = device_info['pin_to_net']

            # Check if substrate connection already exists
            if 'B' not in pin_to_net:
                # Determine MOS type by model and assign default substrate
                if 'nfet' in model or 'nmos' in model:  # NMOS
                    # Prefer existing GND-equivalent node in the netlist
                    existing_gnd = None
                    for net in pin_to_net.values():
                        if net in gnd_equivalents:
                            existing_gnd = net
                            break
                    # Default to 'GND' if no existing GND node found
                    substrate_net = existing_gnd if existing_gnd else 'GND'
                    pin_to_net['B'] = substrate_net
                    print(f"   NMOS {device_name}: added default substrate B -> {substrate_net}")
                elif 'pfet' in model or 'pmos' in model:  # PMOS
                    pin_to_net['B'] = 'VDD'
                    print(f"   PMOS {device_name}: added default substrate B -> VDD")
            else:
                # Validate existing substrate connection
                current_substrate = pin_to_net['B']
                if ('nfet' in model or 'nmos' in model) and current_substrate not in gnd_equivalents and current_substrate != 'VDD':
                    print(f"   ⚠️ NMOS {device_name} substrate connected to non-GND: B -> {current_substrate}")
                elif ('pfet' in model or 'pmos' in model) and current_substrate != 'VDD' and current_substrate not in gnd_equivalents:
                    print(f"   ⚠️ PMOS {device_name} substrate connected to non-VDD: B -> {current_substrate}")
                else:
                    print(f"   MOS {device_name} has existing substrate: B -> {current_substrate}")

    def _extract_all_nets(self, devices):
        """Extract all nets (including substrate connections)"""
        net_connections = {}

        for device_name, device_info in devices.items():
            for pin, net in device_info['pin_to_net'].items():
                if net not in net_connections:
                    net_connections[net] = []
                net_connections[net].append(device_name)

        return {net: devices for net, devices in net_connections.items()
                if len(devices) > 1}

    def _generate_report(self, netlist_data, all_nets, device_pins, routing_nets, output_dir):
        """Generate conversion report"""
        report_file = os.path.join(output_dir, "conversion_report.txt")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write("Netlist to A* Routing Conversion Report\n")
            f.write("=" * 50 + "\n\n")

            f.write("1. Device Info:\n")
            for device, info in netlist_data['devices'].items():
                f.write(f"   {device}: type={info['type']}, pin_net={info['pin_to_net']}\n")

            f.write(f"\n2. All Net Connections ({len(all_nets)}):\n")
            for net, devices in all_nets.items():
                f.write(f"   {net}: connected_devices={devices}\n")

            f.write(f"\n3. Device Pin Coordinates:\n")
            for device, pins in device_pins.items():
                f.write(f"   {device}: {pins}\n")

            f.write(f"\n4. Routing Nets:\n")
            for net in routing_nets:
                f.write(f"   {net['netName']}(ID:{net['netID']}): {net['numPins']} pins\n")
                for i in range(net['numPins']):
                    pin_key = str(i + 1)
                    if pin_key in net:
                        coord = net[pin_key]
                        f.write(f"     Pin{i+1}: ({coord[0]}, {coord[1]}, layer{coord[2]})\n")

        print(f"📄 Conversion report generated: {report_file}")

    def parse_routing_solution(self, solution_file):
        """Parse routing solution file"""
        if not solution_file or not os.path.exists(solution_file):
            return []

        routes = []
        try:
            with open(solution_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line == '!' or (line[0].isalpha() and ' ' in line):
                        continue
                    if line.startswith('(') and ')-(' in line:
                        seg = line[1:-1]
                        a_str, b_str = seg.split(')-(')
                        a = tuple(map(int, a_str.split(',')))
                        b = tuple(map(int, b_str.split(',')))
                        routes.append((a, b))
        except Exception as e:
            print(f"⚠️ Error parsing routing solution: {e}")
        return routes

    def parse_device_contours(self, device_contours_file):
        """Parse device contour definitions"""
        contours = {}
        if not device_contours_file or not os.path.exists(device_contours_file):
            print(f"⚠️ Device contour file not found: {device_contours_file}")
            return contours

        try:
            with open(device_contours_file, 'r') as file:
                # Skip header and separator lines
                next(file)
                next(file)
                for line in file:
                    parts = line.split('|')
                    if len(parts) < 6:
                        continue
                    name = parts[0].strip()
                    try:
                        corners = [tuple(map(int, part.strip().replace('(', '').replace(')', '').split(',')))
                                 for part in parts[1:5]]
                        rotation = int(parts[5].strip().replace('°', ''))
                        contours[name] = {'corners': corners, 'rotation': rotation}
                    except Exception as e:
                        print(f"⚠️ Error parsing device {name}: {e}")
        except Exception as e:
            print(f"⚠️ Error reading contour file: {e}")
        return contours

    def apply_placement_transform(self, contours, offset_x, offset_y, tile_size=1):
        """Transform coordinates to physical grid"""
        phys_contours = {}
        for name, info in contours.items():
            try:
                transformed_corners = []
                for (x, y) in info['corners']:
                    x_transformed = (x + offset_x) * tile_size
                    y_transformed = (y + offset_y) * tile_size
                    transformed_corners.append((x_transformed, y_transformed))
                phys_contours[name] = {
                    'corners': transformed_corners,
                    'rotation': info['rotation']
                }
            except Exception as e:
                print(f"⚠️ Error transforming device {name}: {e}")
        return phys_contours

    def visualize_placement_and_routing(
        self,
        net_to_pins,
        solution_file,
        device_contours_file,
        offset_x,
        offset_y,
        tile_size=1,
        save_dir=None
    ):
        """Visualize placement and routing results"""
        # Ensure save directory is valid and exists
        if not save_dir:
            save_dir = os.path.join(os.getcwd(), "results")
        os.makedirs(save_dir, exist_ok=True)
        print(f"📊 Generating visualization images, save dir: {save_dir}")

        # Define 2D image path
        img2d_path = os.path.join(save_dir, "Placement_and_Routing_2D_with_Contours.jpg")

        try:
            # Parse device contours
            raw_contours = self.parse_device_contours(device_contours_file)
            if not raw_contours:
                print("⚠️ No valid device contour data found, visualization may be affected")

            # Transform coordinates
            phys_contours = self.apply_placement_transform(raw_contours, offset_x, offset_y, tile_size)

            # Collect all pins
            all_pins = []
            for pins in net_to_pins.values():
                all_pins.extend(pins)
            print(f"   Found {len(all_pins)} pins")

            # Parse routing (if any)
            routes = self.parse_routing_solution(solution_file)
            print(f"   Found {len(routes)} route segments")

            # Draw 2D plot
            plt.figure(figsize=(14, 10))
            ax = plt.gca()
            ax.set_aspect('equal')

            # Draw routing
            for (x1, y1, z1), (x2, y2, z2) in routes:
                color = 'blue' if z1 == 1 else 'red'
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=2.0, zorder=3)

            # Draw pins
            if all_pins:
                px = [p[0] for p in all_pins]
                py = [p[1] for p in all_pins]
                ax.scatter(px, py, s=120, facecolors='white', edgecolors='black',
                           linewidth=1.8, zorder=5, label='Pins')

            # Draw device contours
            for name, info in phys_contours.items():
                corners = info['corners']
                rot = info['rotation']

                # Ensure valid corner data
                if len(corners) < 4:
                    print(f"⚠️ Device {name} contour data incomplete, skipping")
                    continue

                try:
                    # Create polygon
                    polygon = patches.Polygon(
                        corners,
                        closed=True,
                        edgecolor='black',
                        facecolor='none',
                        lw=2,
                        zorder=2
                    )

                    # Apply rotation
                    if rot == 90:
                        # Rotate around bottom-left corner
                        rot_center = corners[3]
                        t = Affine2D().rotate_deg_around(rot_center[0], rot_center[1], 90) + ax.transData
                        polygon.set_transform(t)

                    ax.add_patch(polygon)
                    # Add device name
                    ax.text(corners[0][0], corners[0][1], name, fontsize=8,
                            verticalalignment='bottom', horizontalalignment='left')
                except Exception as e:
                    print(f"⚠️ Error drawing device {name}: {e}")

            # Set chart properties
            ax.grid(True)
            ax.set_xlabel("X Coordinate")
            ax.set_ylabel("Y Coordinate")
            ax.set_title("Placement & Routing Visualization (2D)")
            ax.legend()

            # Adjust axis range to ensure all elements are visible
            if all_pins or phys_contours:
                # Collect all key points for axis range adjustment
                all_x = []
                all_y = []

                if all_pins:
                    all_x.extend(px)
                    all_y.extend(py)

                for info in phys_contours.values():
                    for (x, y) in info['corners']:
                        all_x.append(x)
                        all_y.append(y)

                # Add margin
                if all_x and all_y:
                    x_min, x_max = min(all_x), max(all_x)
                    y_min, y_max = min(all_y), max(all_y)
                    margin = (x_max - x_min) * 0.1 if x_max != x_min else 10
                    ax.set_xlim(x_min - margin, x_max + margin)
                    ax.set_ylim(y_min - margin, y_max + margin)

            # Save 2D image
            try:
                plt.tight_layout()
                plt.savefig(img2d_path, dpi=300, bbox_inches='tight')
                if os.path.exists(img2d_path) and os.path.getsize(img2d_path) > 0:
                    print(f"✅ 2D image saved: {img2d_path}")
                else:
                    print(f"❌ 2D image save failed, file may be corrupt")
            except Exception as e:
                print(f"❌ Error saving 2D image: {e}")
            finally:
                plt.close()

            # Draw 3D plot
            img3d_path = os.path.join(save_dir, "Placement_and_Routing_3D_with_Contours.jpg")
            try:
                fig = plt.figure(figsize=(14, 10))
                ax3d = fig.add_subplot(111, projection='3d')
                ax3d.set_zlim(0.75, 2.25)
                ax3d.grid(True)
                ax3d.set_xlabel("X Coordinate")
                ax3d.set_ylabel("Y Coordinate")
                ax3d.set_zlabel("Metal Layer")
                ax3d.set_title("Placement & Routing Visualization (3D)")

                # Draw routing
                for (x1, y1, z1), (x2, y2, z2) in routes:
                    color = 'blue' if z1 == 1 else 'red'
                    ax3d.plot([x1, x2], [y1, y2], [z1, z2], color=color, linewidth=2.0)

                # Draw pins
                if all_pins:
                    px = [p[0] for p in all_pins]
                    py = [p[1] for p in all_pins]
                    pz = [p[2] for p in all_pins]
                    ax3d.scatter(px, py, pz, s=120, facecolors='white',
                                edgecolors='black', linewidth=1.8, label='Pins')

                # Draw device contours
                for name, info in phys_contours.items():
                    corners = info['corners']
                    xs = [c[0] for c in corners] + [corners[0][0]]
                    ys = [c[1] for c in corners] + [corners[0][1]]
                    zs = [0] * 5
                    ax3d.plot(xs, ys, zs, color='black', linewidth=2)

                    # Device name
                    cx = sum(c[0] for c in corners) / 4
                    cy = sum(c[1] for c in corners) / 4
                    ax3d.text(cx, cy, 0.1, name, fontsize=8, ha='center', va='bottom')

                ax3d.legend()
                plt.tight_layout()
                plt.savefig(img3d_path, dpi=300, bbox_inches='tight')
                print(f"✅ 3D image saved: {img3d_path}")
            except Exception as e:
                print(f"❌ Error saving 3D image: {e}")
            finally:
                plt.close()

        except Exception as e:
            print(f"❌ Error during visualization: {e}")
            import traceback
            traceback.print_exc()
        else:
            print(f"✅ All visualization images generated")

def main():
    """Main entry point"""
    print("🎯 Netlist to A* Routing Conversion Tool")
    print("=" * 50)

    # Configure file paths
    netlist_file = "./cache/auto_placement/netlist_for_routing.txt"
    placement_file_pin = "./cache/auto_placement/placement.txt"
    output_dir = "./cache/autoRouting"

    # Check input files
    if not os.path.exists(netlist_file):
        print(f"❌ Netlist file not found: {netlist_file}")
        return False

    if not os.path.exists(placement_file_pin):
        print(f"❌ Placement file not found: {placement_file_pin}")
        return False

    # Execute conversion
    converter = NetlistToRoutingConverter(tile_size=1)
    success = converter.convert_and_route(netlist_file, placement_file_pin, output_dir)

    if success:
        print("\n🎉 Conversion completed successfully!")
        print(f"📂 Check results folder: {output_dir}")
        return True
    else:
        print("\n❌ Conversion failed, check error messages")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
