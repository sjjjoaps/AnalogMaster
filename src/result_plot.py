import os
import re
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from collections import defaultdict

# =============================================
# 1. Parse device contour file (with rotation)
# =============================================
def parse_device_contours(file_path):
    """
    Parse device contour information from a txt file.
    Returns: {device_name: {'x_lb': x, 'y_lb': y, 'width': w, 'height': h, 'rotation': deg}}
    """
    devices = {}
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or line.startswith('Device Name') or line.startswith('-'):
            continue

        # Split using regex, compatible with spaces and pipes
        parts = [p.strip() for p in re.split(r'\s*\|\s*', line) if p.strip()]
        if len(parts) < 6:
            continue

        name = parts[0]
        try:
            lt = eval(parts[1])  # top-left
            rt = eval(parts[2])  # top-right
            rb = eval(parts[3])  # bottom-right
            lb = eval(parts[4])  # bottom-left
            rot_str = parts[5]
            rot = int(re.search(r'\d+', rot_str).group())
        except Exception as e:
            print(f"Error parsing device {name}: {e}")
            continue

        # Default to bottom-left as reference
        x_lb, y_lb = lb
        width = abs(rt[0] - lt[0])
        height = abs(lb[1] - lt[1])

        devices[name] = {
            'x_lb': x_lb,
            'y_lb': y_lb,
            'width': width,
            'height': height,
            'rotation': rot
        }
    return devices

# =============================================
# 2. Apply offset + tile_size to convert to physical coordinates
# =============================================
def apply_placement_transform(device_contours, offset_x, offset_y, tile_size=10):
    """
    Convert original layout coordinates (with contours) to physical grid coordinates.
    Returns: {device_name: {'x': x_phys, 'y': y_phys, 'w': w_phys, 'h': h_phys, 'rot': deg}}
    """
    transformed = {}
    for name, info in device_contours.items():
        x_phys = int((info['x_lb'] + offset_x) * tile_size)
        y_phys = int((info['y_lb'] + offset_y) * tile_size)
        w_phys = int(info['width'] * tile_size)
        h_phys = int(info['height'] * tile_size)
        transformed[name] = {
            'x': x_phys,
            'y': y_phys,
            'width': w_phys,
            'height': h_phys,
            'rotation': info['rotation']
        }
    return transformed

# =============================================
# 3. Parse A* routing result
# =============================================
def parse_routing_solution(solution_file):
    routes = []
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
    return routes

# =============================================
# 4. Main plotting function (2D + 3D)
# =============================================
def visualize_placement_and_routing(
    net_to_pins,
    solution_file,
    device_contours_file,
    offset_x,
    offset_y,
    tile_size=10,
    save_dir=None
):
    if save_dir is None:
        save_dir = os.path.dirname(solution_file) or "."

    # Step 1: Convert device contours to physical coordinates
    raw_contours = parse_device_contours(device_contours_file)
    phys_contours = apply_placement_transform(raw_contours, offset_x, offset_y, tile_size)

    # Step 2: Get all pins (from net_to_pins)
    all_pins = []
    for pins in net_to_pins.values():
        all_pins.extend(pins)

    # Step 3: Parse routing
    routes = parse_routing_solution(solution_file)

    # ========================
    # 2D plot
    # ========================
    fig2d, ax2d = plt.subplots(figsize=(14, 10))
    ax2d.set_aspect('equal')

    # Draw routing
    for (x1, y1, z1), (x2, y2, z2) in routes:
        color = 'blue' if z1 == 1 else 'red'
        ax2d.plot([x1, x2], [y1, y2], color=color, linewidth=2.0, zorder=2)

    # Draw pins
    if all_pins:
        px = [p[0] for p in all_pins]
        py = [p[1] for p in all_pins]
        ax2d.scatter(px, py, s=120, facecolors='white', edgecolors='black', linewidth=1.8, zorder=5)

    # Draw device contours (consider rotation)
    for name, info in phys_contours.items():
        x, y = info['x'], info['y']
        w, h = info['width'], info['height']
        rot = info['rotation']

        if rot == 0:
            rect = plt.Rectangle((x, y), w, h, edgecolor='black', facecolor='none', lw=2, zorder=3)
            ax2d.add_patch(rect)
        elif rot == 90:
            # 90-degree rotation: use bottom-left as origin, draw rectangle then rotate
            # Matplotlib's rotate_around needs center point, we use transform instead
            from matplotlib.patches import Rectangle
            import matplotlib.transforms as mtransforms
            rect = Rectangle((x, y), w, h, edgecolor='black', facecolor='none', lw=2, zorder=3)
            t = mtransforms.Affine2D().rotate_deg_around(x, y, 90) + ax2d.transData
            rect.set_transform(t)
            ax2d.add_patch(rect)
        else:
            # Other angles can be extended
            rect = plt.Rectangle((x, y), w, h, edgecolor='black', facecolor='none', lw=2, zorder=3)
            ax2d.add_patch(rect)

    ax2d.invert_yaxis()
    ax2d.axis('off')
    plt.savefig(os.path.join(save_dir, "Placement_and_Routing_2D_with_Contours.jpg"), dpi=200, bbox_inches='tight')
    plt.close()

    # ========================
    # 3D plot (simplified: no rotation handling)
    # ========================
    fig3d = plt.figure(figsize=(14, 10))
    ax3d = fig3d.add_subplot(111, projection='3d')
    ax3d.set_zlim(0.75, 2.25)
    plt.axis('off')

    # Routing
    for (x1, y1, z1), (x2, y2, z2) in routes:
        color = 'blue' if z1 == 1 else 'red'
        ax3d.plot([x1, x2], [y1, y2], [z1, z2], color=color, linewidth=2.0)

    # Pins
    if all_pins:
        px = [p[0] for p in all_pins]
        py = [p[1] for p in all_pins]
        pz = [p[2] for p in all_pins]
        ax3d.scatter(px, py, pz, s=120, facecolors='white', edgecolors='black', linewidth=1.8)

    # Device contours (3D simplified as bottom rectangles, ignore rotation)
    for name, info in phys_contours.items():
        x, y = info['x'], info['y']
        w, h = info['width'], info['height']
        # Draw bottom rectangle (z=0)
        xx = [x, x + w, x + w, x, x]
        yy = [y, y, y - h, y - h, y]  # Note y-axis direction (consistent with 2D)
        zz = [0, 0, 0, 0, 0]
        ax3d.plot(xx, yy, zz, color='black', linewidth=2)

    plt.savefig(os.path.join(save_dir, "Placement_and_Routing_3D_with_Contours.jpg"), dpi=200, bbox_inches='tight')
    plt.close()

    print(f"Layout+routing+device contour visualization completed! Images saved to: {save_dir}")
