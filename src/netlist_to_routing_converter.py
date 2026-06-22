#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Netlist to A* Routing Format Converter
Convert SPICE netlist and device placement to .gr format required by A* algorithm
"""

import re
import numpy as np
from typing import Dict, List, Tuple, Set
import os


class PlacementParser:
    """Device placement parser (supports pin-level coordinates)"""

    def __init__(self):
        self.device_pins = {}  # device -> {pin_name: (x, y)}

    def parse_placement(self, placement_file: str) -> Dict:
        with open(placement_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # Skip header and separator line
        start_parsing = False
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Start parsing after the separator line below the header (supports any length)
            if line.startswith('---') and '---' in line:
                start_parsing = True
                continue

            if start_parsing and '|' in line:
                # Split and clean fields, preserving all positions (including empty values)
                parts = [p.strip() for p in line.split('|')]
                # Ensure at least 6 fields (device name + 4 possible coordinate columns + type)
                if len(parts) < 6:
                    print(f"Warning: Incomplete line format, skipping: {line}")
                    continue

                device_name = parts[0]
                device_type = parts[5] if len(parts) > 5 else "Unknown type"

                if not device_name:
                    continue

                pin_coords = {}

                if device_type == 'MOSFET':
                    # MOSFET: fixed parsing of D/G/S/B four pins (corresponding to columns 1-4)
                    pin_mapping = {
                        'D': parts[1],
                        'G': parts[2],
                        'S': parts[3],
                        'B': parts[4]
                    }
                    for pin_name, coord_str in pin_mapping.items():
                        if coord_str in ['—', '-', '']:
                            continue
                        try:
                            coord_clean = coord_str.strip('()')
                            x, y = map(float, coord_clean.split(','))
                            pin_coords[pin_name] = (x, y)
                        except Exception as e:
                            print(f"Warning: Failed to parse {pin_name} coordinate for {device_name}: {coord_str}, error: {e}")

                elif device_type == 'Resistor':
                    # Resistor: extract all valid coordinates from columns 1-4, use as pins 1 and 2 in order
                    valid_coords = []
                    # Check resistor possible coordinate columns (1-4)
                    for coord_str in parts[1:5]:
                        if coord_str not in ['—', '-', '']:
                            try:
                                coord_clean = coord_str.strip('()')
                                x, y = map(float, coord_clean.split(','))
                                valid_coords.append((x, y))
                            except:
                                continue

                    # Ensure resistor has two valid pins (adjust tolerance logic based on actual scenario)
                    if len(valid_coords) >= 2:
                        pin_coords['D'] = valid_coords[0]
                        pin_coords['S'] = valid_coords[1]
                    else:
                        print(f"Warning: Resistor {device_name} has insufficient valid coordinates (found {len(valid_coords)}, need at least 2)")

                else:
                    print(f"Warning: Unknown device type '{device_type}', skipping {device_name}")
                    continue

                self.device_pins[device_name] = pin_coords

        return self.device_pins


class NetlistParser:
    """SPICE netlist parser"""

    def __init__(self):
        self.devices = {}  # Device information
        self.external_nodes = set()  # External nodes

    # def parse_netlist(self, netlist_file: str) -> Dict:
    #     with open(netlist_file, 'r') as f:
    #         content = f.read()
    #
    #     lines = content.strip().split('\n')
    #     self.devices = {}
    #     self.external_nodes = set()
    #
    #     # External node patterns
    #     external_patterns = [r'^V\w+', 'VDD', 'VSS', 'GND', '0', 'VIN', 'Vin', 'DC', 'AC', 'circuit.gnd', 'Vb']
    #
    #     for line in lines:
    #         line = line.strip()
    #         if not line or line.startswith(('.', '#')):
    #             continue
    #
    #         parts = line.split()
    #         if not parts:
    #             continue
    #
    #         device_name = parts[0]
    #
    #         # Handle external nodes like voltage sources
    #         if any(re.search(p, device_name, re.IGNORECASE) for p in external_patterns):
    #             if len(parts) >= 3:
    #                 self.external_nodes.update(parts[1:3])
    #             continue
    #
    #         # Handle MOSFET (starts with XM)
    #         if device_name.startswith('XM'):
    #             # Netlist format: XM1 Node3 Vin1 Node4 Node4 sky130_fd_pr__nfet_01v8 ...
    #             # Pin order: D, G, S, B
    #             if len(parts) >= 5:
    #                 pin_nets = parts[1:5]  # first 4 are pin connections
    #                 model = parts[5]
    #
    #                 # MOSFET: D, G, S, B (using first 3 valid pins)
    #                 pin_names = ['D', 'G', 'S', 'B']
    #                 pin_names = pin_names[:len(pin_nets)]
    #
    #                 # Build pin_name -> net_name mapping
    #                 pin_to_net = {}
    #                 for name, net in zip(pin_names, pin_nets):
    #                     pin_to_net[name] = net
    #
    #                 self.devices[device_name] = {
    #                     'pin_to_net': pin_to_net,
    #                     'type': model
    #                 }
    #
    #         # Handle resistor (starts with R)
    #         elif device_name.startswith('R'):
    #             # Netlist format: RRD1 VDD Node3 20000Ohm
    #             # Pin order: D, S
    #             if len(parts) >= 3:
    #                 pin_nets = parts[1:3]  # first 2 are pin connections
    #
    #                 # Resistor only has two pins D and S
    #                 pin_names = ['D', 'S']
    #                 pin_names = pin_names[:len(pin_nets)]
    #
    #                 # Build pin_name -> net_name mapping
    #                 pin_to_net = {}
    #                 for name, net in zip(pin_names, pin_nets):
    #                     pin_to_net[name] = net
    #
    #                 self.devices[device_name] = {
    #                     'pin_to_net': pin_to_net,
    #                     'type': 'resistor'
    #                 }
    #
    #     # Add common external nodes
    #     common_external = {'VDD', 'VSS', 'GND', '0', 'Vdd', 'Vss', 'VIN1', 'Vin1', 'VIN2', 'Vin2', 'Vb', 'circuit.gnd','Vout1','Vout2','VOUT','Vout'}
    #     self.external_nodes.update(common_external)
    #
    #     return {'devices': self.devices, 'external_nodes': self.external_nodes}
    def parse_netlist(self, netlist_file: str) -> Dict:
        with open(netlist_file, 'r') as f:
            content = f.read()

        lines = content.strip().split('\n')
        self.devices = {}
        self.external_nodes = set()

        for line in lines:
            line = line.strip()
            if not line or line.startswith(('.', '#')):
                continue

            parts = line.split()
            if not parts:
                continue

            device_name = parts[0]

            # Handle MOSFET (starts with XM)
            if device_name.startswith('XM'):
                # Netlist format: XM1 Node3 Vin1 Node4 Node4 sky130_fd_pr__nfet_01v8 ...
                # Pin order: D, G, S, B
                if len(parts) >= 5:
                    pin_nets = parts[1:5]  # first 4 are pin connections (allow external nodes)
                    model = parts[5]

                    # MOSFET: D, G, S, B (using first 4 pins)
                    pin_names = ['D', 'G', 'S', 'B'][:len(pin_nets)]

                    # Build pin_name -> net_name mapping (including external nodes)
                    pin_to_net = {name: net for name, net in zip(pin_names, pin_nets)}

                    self.devices[device_name] = {
                        'pin_to_net': pin_to_net,
                        'type': model
                    }

            # Handle resistor (starts with R)
            elif device_name.startswith('R'):
                # Netlist format: RRD1 VDD Node3 20000Ohm
                # Pin order: D, S
                if len(parts) >= 3:
                    pin_nets = parts[1:3]  # first 2 are pin connections

                    # Resistor pins
                    pin_names = ['D', 'S'][:len(pin_nets)]

                    # Build pin_name -> net_name mapping
                    pin_to_net = {name: net for name, net in zip(pin_names, pin_nets)}

                    self.devices[device_name] = {
                        'pin_to_net': pin_to_net,
                        'type': 'resistor'
                    }
        return {'devices': self.devices, 'external_nodes': self.external_nodes}

    def extract_internal_nets(self) -> Dict[str, List[str]]:
        """Extract connection nets between internal devices"""
        net_connections = {}
        print(self.devices)
        # Collect all nets and devices connected to them
        for device_name, device_info in self.devices.items():
            # Fix bug in original code, use pin_to_net instead of nets
            for net in device_info['pin_to_net'].values():
                if net not in self.external_nodes:  # Exclude external nodes
                    if net not in net_connections:
                        net_connections[net] = []
                    net_connections[net].append(device_name)

        # Keep only nets connected to multiple devices (true internal connections)
        internal_nets = {net: devices for net, devices in net_connections.items()
                        if len(devices) > 1}
        print(internal_nets)
        return internal_nets

class RoutingGridGenerator:
    def __init__(self, tile_size=1):
        self.tile_size = tile_size  # units per tile

    def build_net_to_pins(self, devices, device_pins):
        """Build net -> [(x, y, layer), ...] mapping, treating GND and 0 as the same network"""
        # Define GND equivalent node mapping
        gnd_equivalents = {'0': 'GND', 'VSS': 'GND', 'circuit.gnd': 'GND'}

        print("=== Debug: Input device list ===")
        print("Netlist devices:", list(devices.keys()))
        print("Placement devices:", list(device_pins.keys()))

        # Collect all pin coordinates, calculate global offset (ensure all coordinates > 0)
        all_coords = []
        for device_name, pin_coords in device_pins.items():
            for coord in pin_coords.values():
                all_coords.append(coord)

        if not all_coords:
            offset_x = offset_y = 1  # Safe default, ensure > 0
            print("No valid coordinates, using default offset (1, 1)")
        else:
            min_x = min(c[0] for c in all_coords)
            min_y = min(c[1] for c in all_coords)
            offset_x = 1 - min_x
            offset_y = 1 - min_y
            print(f"Coordinate range: min=({min_x}, {min_y}) -> offset: offset_x={offset_x}, offset_y={offset_y}")

        # Build net -> pin physical coordinate list (no longer filter external nodes)
        net_to_pins = {}

        print("\n=== Debug: Per-pin processing ===")
        for device_name, dev_info in devices.items():
            if device_name not in device_pins:
                print(f"Skipping {device_name}: device not found in placement file")
                continue

            pin_coords = device_pins[device_name]      # {'D': (9, -1), 'G': (8, 0), ...}
            pin_to_net = dev_info['pin_to_net']        # {'D': 'Node3', 'G': 'Vin1', ...}
            print(f"   Pin connections: {pin_to_net}")
            print(f"   Pin coordinates: {pin_coords}")
            print(f"\nProcessing device: {device_name}")
            for pin_name, net_name in pin_to_net.items():
                # Handle GND equivalent nodes, normalize to 'GND'
                normalized_net = gnd_equivalents.get(net_name, net_name)

                if pin_name not in pin_coords:
                    print(f"   {device_name}.{pin_name} -> {normalized_net}: pin coordinates not found in placement!")
                    continue

                raw_x, raw_y = pin_coords[pin_name]
                x_shifted = raw_x + offset_x
                y_shifted = raw_y + offset_y
                x_phys = int(x_shifted * self.tile_size)
                y_phys = int(y_shifted * self.tile_size)
                pin_phys = (x_phys, y_phys, 1)  # layer=1

                print(f"   {device_name}.{pin_name} -> {normalized_net}")
                print(f"        Original: ({raw_x}, {raw_y}) -> Shifted: ({x_shifted:.2f}, {y_shifted:.2f}) -> Physical: {pin_phys}")

                if normalized_net not in net_to_pins:
                    net_to_pins[normalized_net] = []
                net_to_pins[normalized_net].append(pin_phys)

        # Keep only nets with >= 2 pins (core filter condition)
        filtered_nets = {}
        print("\n=== Filter: Keep only nets with >= 2 pins ===")
        for net, pins in net_to_pins.items():
            if len(pins) >= 2:
                filtered_nets[net] = pins
                print(f"   Keeping {net}: {len(pins)} pins")
            else:
                print(f"   Discarding {net}: only {len(pins)} pin(s)")

        net_to_pins = filtered_nets

        print("\n=== Final net_to_pins result ===")
        for net, pins in net_to_pins.items():
            print(f"{net}: {len(pins)} pins -> {pins}")

        return net_to_pins, offset_x, offset_y

    def generate_routing_nets(self, net_to_pins):
        """Generate routing_nets list required by A*"""
        routing_nets = []
        net_id = 1

        for net_name, pins in net_to_pins.items():
            net_info = {
                'netName': f"A{net_id}",
                'netID': net_id,
                'numPins': len(pins),
                'minWidth': 1
            }
            for i, pin in enumerate(pins):
                net_info[str(i+1)] = list(pin)  # [x, y, layer]
            routing_nets.append(net_info)
            net_id += 1

        return routing_nets



class RoutingFormatGenerator:
    """A* routing format generator"""

    def __init__(self, grid_generator: RoutingGridGenerator):
        self.grid_gen = grid_generator

    def generate_gr_file(self, routing_nets: List[Dict], output_file: str):
        # Calculate required grid size
        all_x = []
        all_y = []
        for net in routing_nets:
            for i in range(net['numPins']):
                pin = net[str(i+1)]
                all_x.append(pin[0])
                all_y.append(pin[1])

        max_x = max(all_x) if all_x else 160
        max_y = max(all_y) if all_y else 160
        grid_w = int(max_x // self.grid_gen.tile_size) + 2
        grid_h = int(max_y // self.grid_gen.tile_size) + 2
        grid_w = max(16, grid_w)
        grid_h = max(16, grid_h)

        with open(output_file, 'w') as f:
            f.write(f"grid {grid_w} {grid_h} 2\n")
            f.write("vertical capacity 0 4\n")
            f.write("horizontal capacity 4 0\n")
            f.write("minimum width 1 1\n")
            f.write("minimum spacing 0 0\n")
            f.write("via spacing 0 0\n")
            f.write(f"0 0 {self.grid_gen.tile_size} {self.grid_gen.tile_size}\n")
            f.write(f"num net {len(routing_nets)}\n")

            for net in routing_nets:
                f.write(f"{net['netName']} {net['netID']:02d} {net['numPins']} 1\n")
                for i in range(net['numPins']):
                    x, y, z = net[str(i+1)]
                    f.write(f"{int(x)}  {int(y)} {int(z)}\n")

            f.write("0\n")


def test_conversion():
    print("=== Start conversion flow test ===")

    # 1. Parse netlist
    netlist_parser = NetlistParser()
    netlist_file = 'best_netlist.txt'
    netlist_data = netlist_parser.parse_netlist(netlist_file)
    internal_nets = netlist_parser.extract_internal_nets()  # Can be kept for debugging

    # 2. Parse placement (pin-level)
    placement_parser = PlacementParser()
    placement_file = 'placement.txt'
    device_pins = placement_parser.parse_placement(placement_file)

    # 3. Generate net -> pins mapping
    grid_gen = RoutingGridGenerator(tile_size=10)
    net_to_pins = grid_gen.build_net_to_pins(
        netlist_data['devices'],
        device_pins,
        netlist_data['external_nodes']
    )

    print("Net pin mapping:")
    for net, pins in net_to_pins.items():
        print(f"  {net}: {pins}")

    # 4. Generate routing_nets
    routing_nets = grid_gen.generate_routing_nets(net_to_pins)

    # 5. Output .gr file
    format_gen = RoutingFormatGenerator(grid_gen)
    output_file = 'converted_netlist.gr'
    format_gen.generate_gr_file(routing_nets, output_file)

    print(f"\nSuccessfully generated {len(routing_nets)} nets to {output_file}")

def test_parsing():
    """Test parsing functionality"""
    print("=== Test netlist parsing ===")

    # Test netlist parsing
    netlist_parser = NetlistParser()
    netlist_file = './data/best_netlist.txt'

    try:
        netlist_data = netlist_parser.parse_netlist(netlist_file)
        print("Device information:")
        for device, info in netlist_data['devices'].items():
            print(f"  {device}: {info}")

        print(f"\nExternal nodes: {netlist_data['external_nodes']}")

        internal_nets = netlist_parser.extract_internal_nets()
        print(f"\nInternal net connections:")
        for net, devices in internal_nets.items():
            print(f"  {net} -> {devices}")

    except Exception as e:
        print(f"Netlist parsing error: {e}")
        return False

    print("\n=== Test placement parsing ===")

    # Test placement parsing
    placement_parser = PlacementParser()
    placement_file = './data/placement.txt'

    try:
        placement_data = placement_parser.parse_placement(placement_file)
        print("Device placement info:")
        for device, info in placement_data.items():
            print(f"  {device}: center=({info['center'][0]:.2f}, {info['center'][1]:.2f})")

    except Exception as e:
        print(f"Placement parsing error: {e}")
        return False

    return True


if __name__ == "__main__":
    # test_parsing()  # Basic parsing test
    test_conversion()  # Full conversion test
