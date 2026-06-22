from .complete_converter import NetlistToRoutingConverter
import os
def Routing_pipline(netlist_file, placement_file, output_dir):
    # Placement file refers to XM3        | (16, 0)      | (11, 5)      | (6, 0)       | MOSFET
    """Main function"""
    print("Netlist to A* Routing Conversion Tool")
    print("=" * 50)
    # Check input files
    if not os.path.exists(netlist_file):
        print(f"Netlist file does not exist: {netlist_file}")
        return False

    if not os.path.exists(placement_file):
        print(f"Placement file does not exist: {placement_file}")
        return False

    # Execute conversion
    converter = NetlistToRoutingConverter()
    success = converter.convert_and_route(netlist_file, placement_file, output_dir)

    if success:
        print("\nConversion completed successfully!")
        print(f"View results folder: {output_dir}")
        print("   - converted_netlist.gr: A* algorithm input file")
        print("   - solution/: Routing results")
        print("   - conversion_report.txt: Detailed conversion report")
        return True
    else:
        print("\nConversion failed, please check error messages")
        return False
if __name__ == "__main__":
    netlist_file = "./cache/auto_placement/netlist_for_routing.txt"
    placement_file = "./cache/auto_placement/placement.txt"
    output_dir = "./cache/auto_routing/conversion_output"
    success = Routing_pipline(netlist_file, placement_file, output_dir)
