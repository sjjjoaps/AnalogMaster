

import torch
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import re
import time
import random
import math

# Detect GPU availability and set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")

def parse_spice_value(value, param_type=None):
    """Parse SPICE parameter values, converting units to floating-point numbers."""
    if param_type == 'dimension':
        match = re.match(r'([0-9\.]+)', value)
        if match:
            return float(match.group(1))
        raise ValueError(f"Invalid dimension value: {value}")
    
    if param_type == 'resistance':
        units = {'f': 1e-15, 'p': 1e-12, 'n': 1e-9, 'u': 1e-6, 'm': 1e-3, 'k': 1e3, 'meg': 1e6, 'g': 1e9}
        value = re.sub(r'[Oo][Hh][Mm]$', '', value)
        match = re.match(r'([0-9\.]+)([a-zA-Z]*)', value)
        if match:
            num = float(match.group(1))
            unit = match.group(2).lower()
            if unit in units:
                return num * units[unit]
            return num
        raise ValueError(f"Invalid resistance value: {value}")
    
    match = re.match(r'([0-9\.]+)', value)
    if match:
        return float(match.group(1))
    return 0.0

def parse_spice_netlist(file_path, multi=False):
    devices = []
    node_to_devices = {}
    device_name_to_index = {}
    logical_groups = {}
    index = 0

    # Read file content or process string directly
    if '\n' in file_path:
        lines = file_path.strip().split('\n')
    else:
        with open(file_path, 'r') as f:
            lines = f.readlines()

    for line_num, line in enumerate(lines):
        line = line.strip()
        # Skip comments, command lines, and power/current sources
        if not line or line.startswith(('*', '.', 'V', 'I')):
            continue
            
        # 处理MOSFET (XM开头)、电容(C开头)和电阻(R开头)
        if line.startswith(('XM', 'C', 'R')):
            parts = line.split()
            if len(parts) < 4:  # 新格式需要至少4个部分
                print(f"警告：第 {line_num+1} 行格式不正确，跳过: {line}")
                continue
                
            instance_name = parts[0]
            params = {}
            
            # 判断是否为MOSFET（根据模型名称判断）
            is_mosfet = any(part.startswith('sky130_fd_pr__') for part in parts)
            
            # 提取节点 - 新格式中XM器件有4个节点
            if line.startswith('XM') and is_mosfet:
                nodes = parts[1:5]  # 源极、栅极、漏极、衬底
                model_start = 5
            else:  # 电阻和电容
                nodes = parts[1:3]  # 两个节点
                model_start = 3

            # 提取模型名称（如果有）
            model_name = parts[model_start] if model_start < len(parts) else ""
            
            # 提取参数（从模型名称后的部分开始）
            for param in parts[model_start+1:]:
                if '=' in param:
                    key, value = param.split('=', 1)
                    params[key.strip().lower()] = value.strip()

            # 处理MOSFET
            if line.startswith('XM') and is_mosfet:
                # 提取宽度和长度参数
                w_value = params.get('w', None)
                l_value = params.get('l', None)
                
                if not w_value or not l_value:
                    print(f"警告：晶体管 {instance_name} 缺少 'w' 或 'l' 参数，无法添加到布局")
                    continue
                
                try:
                    w = parse_spice_value(w_value, param_type='dimension')
                    l = parse_spice_value(l_value, param_type='dimension')
                    # 处理并联数和倍数
                    multi_count = int(params.get('mult', '1')) if multi else 1
                    nf = int(params.get('nf', '1'))  # 新增：处理并联数
                    total_count = multi_count * nf
                    
                    base_name = instance_name
                    group_indices = []
                    
                    for m in range(total_count):
                        unique_instance_name = f"{instance_name}_{m}" if total_count > 1 else instance_name
                        devices.append({
                            'name': unique_instance_name, 
                            'type': 'MOSFET',
                            'model': model_name,  # 新增：保存模型名称
                            'width': w, 
                            'height': l,
                            'rotation': 0,
                            'nf': nf,  # 保存并联数
                            'mult': multi_count  # 保存倍数
                        })
                        device_name_to_index[unique_instance_name] = index
                        group_indices.append(index)
                        
                        # 关联节点和器件
                        for node in nodes:
                            if node not in node_to_devices:
                                node_to_devices[node] = []
                            node_to_devices[node].append(index)
                        
                        index += 1
                    
                    if total_count > 1:
                        logical_groups[base_name] = group_indices
                except Exception as e:
                    print(f"解析晶体管 {instance_name} 时出错: {e}")
                    continue
                    
            # 处理电容和电阻
            elif line.startswith(('C', 'R')):
                # 对于R和C，值可能直接作为参数或在parts中
                value = None
                if len(parts) > 3:
                    value = parts[3]
                
                # 尝试从参数中获取尺寸信息
                w_value = params.get('w', None)
                l_value = params.get('l', None)
                
                # 如果没有明确的w和l，尝试从值计算（简单处理）
                if not w_value or not l_value and value:
                    try:
                        val = parse_spice_value(value)
                        # 简单地将值转换为尺寸比例
                        w_value = f"{val**0.5:.3f}u"
                        l_value = f"{val**0.5:.3f}u"
                    except:
                        pass
                
                if w_value and l_value:
                    try:
                        w = parse_spice_value(w_value, param_type='dimension')
                        l = parse_spice_value(l_value, param_type='dimension')
                        dev_type = 'Capacitor' if line.startswith('C') else 'Resistor'
                        
                        devices.append({
                            'name': instance_name, 
                            'type': dev_type,
                            'value': value,  # 保存原始值
                            'width': w, 
                            'height': l,
                            'rotation': 0
                        })
                        device_name_to_index[instance_name] = index
                        
                        for node in nodes:
                            if node not in node_to_devices:
                                node_to_devices[node] = []
                            node_to_devices[node].append(index)
                            
                        index += 1
                    except Exception as e:
                        print(f"解析元件 {instance_name} 时出错: {e}")
                else:
                    print(f"警告：元件 {instance_name} 缺少 'w' 或 'l' 参数，无法添加到布局")
                    continue

    # 整理网络信息（连接两个以上器件的节点）
    nets = [node_to_devices[node] for node in node_to_devices if len(node_to_devices[node]) > 1]
    print(f"解析完成，共找到 {len(devices)} 个器件")
    for dev in devices:
        print(f" - {dev['name']}: {dev['type']}, 宽={dev['width']}, 高={dev['height']}")
    
    # 将W/L转换为网格尺寸，控制尺寸差异
    if devices:
        import numpy as np  # 确保导入numpy
        areas = np.array([dev['width'] * dev['height'] for dev in devices])
        log_areas = np.log(areas + 1e-6)
        norm_log = (log_areas - log_areas.min()) / (log_areas.max() - log_areas.min() + 1e-9)
        
        min_cells = 4   # 最小 2x2
        max_cells = 25  # 最大 5x5
        grid_areas = min_cells + norm_log * (max_cells - min_cells)
        
        # 保留原始比例
        side = np.sqrt(grid_areas)
        W_grid = np.round(side).astype(int)
        H_grid = W_grid  # 正方形近似
                
        # 更新器件尺寸为整数网格单位
        for i, dev in enumerate(devices):
            dev['width_orig'] = dev['width']
            dev['height_orig'] = dev['height']
            dev['width'] = float(W_grid[i])
            dev['height'] = float(H_grid[i])
            dev['width_grid'] = int(W_grid[i])
            dev['height_grid'] = int(H_grid[i])

    if devices:
        print("器件网格尺寸已设定，范围：", 
              f"W: {min(W_grid)}~{max(W_grid)}, H: {min(H_grid)}~{max(H_grid)}")
    
    return devices, nets, device_name_to_index, logical_groups

def get_device_dimensions(device):
    """
    获取器件的有效尺寸（考虑旋转）
    返回: (effective_width, effective_height)
    """
    base_width = device['width']
    base_height = device['height']
    rotation = device.get('rotation', 0)
    
    if rotation == 90:
        # 90度旋转：宽度和高度交换
        return base_height, base_width
    else:
        # 0度（无旋转）
        return base_width, base_height

def compute_hpwl(x, y, nets, devices, alpha=0.1):
    device = x.device
    hpwl = torch.tensor(0.0, device=device, dtype=torch.float32)
    for net in nets:
        indices = torch.tensor(net, device=device)
        x_net = x[indices]
        y_net = y[indices]
        max_x = alpha * torch.logsumexp(x_net / alpha, dim=0)
        min_x = -alpha * torch.logsumexp(-x_net / alpha, dim=0)
        max_y = alpha * torch.logsumexp(y_net / alpha, dim=0)
        min_y = -alpha * torch.logsumexp(-y_net / alpha, dim=0)
        hpwl += (max_x - min_x) + (max_y - min_y)
    return hpwl

def compute_overlap(x, y, devices, overlap_power=3, max_overlap_penalty=1e8, debug=False):
    """
    计算重叠惩罚，修复了标准化导致的重叠检测错误，并支持器件旋转
    """
    device = x.device
    n_devices = len(devices)
    
    # 获取考虑旋转后的有效尺寸
    widths = []
    heights = []
    for dev in devices:
        eff_width, eff_height = get_device_dimensions(dev)
        widths.append(eff_width)
        heights.append(eff_height)
    
    widths = torch.tensor(widths, device=device, dtype=torch.float32)
    heights = torch.tensor(heights, device=device, dtype=torch.float32)
    
    # 不再进行标准化，使用原始尺寸进行重叠计算
    # 标准化会导致尺寸变得极小，而坐标保持原值，从而无法正确检测重叠
    
    if debug:
        print(f"\n调试信息 - 器件数量: {n_devices}")
        print(f"坐标: x={x.cpu().numpy()}, y={y.cpu().numpy()}")
        print(f"有效宽度: {widths.cpu().numpy()}")
        print(f"有效高度: {heights.cpu().numpy()}")
        for i, dev in enumerate(devices):
            eff_w, eff_h = get_device_dimensions(dev)
            print(f"器件{i} {dev['name']}: 原始({dev['width']:.2f}x{dev['height']:.2f}) -> 旋转{dev.get('rotation', 0)}度 -> 有效({eff_w:.2f}x{eff_h:.2f})")
    
    i, j = torch.triu_indices(n_devices, n_devices, offset=1, device=device)
    xi = x[i]
    xj = x[j]
    yi = y[i]
    yj = y[j]
    wi = widths[i]
    wj = widths[j]
    hi = heights[i]
    hj = heights[j]
    
    # 计算重叠区域
    left_i = xi - wi / 2
    right_i = xi + wi / 2
    bottom_i = yi - hi / 2
    top_i = yi + hi / 2
    left_j = xj - wj / 2
    right_j = xj + wj / 2
    bottom_j = yj - hj / 2
    top_j = yj + hj / 2
    
    overlap_width = torch.minimum(right_i, right_j) - torch.maximum(left_i, left_j)
    overlap_height = torch.minimum(top_i, top_j) - torch.maximum(bottom_i, bottom_j)
    
    if debug:
        print(f"\n重叠宽度 (原始): {overlap_width.cpu().numpy()}")
        print(f"重叠高度 (原始): {overlap_height.cpu().numpy()}")
    
    # 只有当重叠宽度和高度都大于0时才计算重叠面积
    overlap_width = torch.clamp(overlap_width, min=0.0)
    overlap_height = torch.clamp(overlap_height, min=0.0)
    
    overlap_area = overlap_width * overlap_height
    
    if debug:
        print(f"重叠面积: {overlap_area.cpu().numpy()}")
        print(f"总重叠面积: {torch.sum(overlap_area).item()}")
    
    # 计算惩罚并限制最大值
    overlap_penalty = torch.sum(torch.clamp(overlap_area ** overlap_power, max=max_overlap_penalty))
    total_overlap_area = torch.sum(overlap_area)
    
    return overlap_penalty, total_overlap_area

def compute_symmetry(x, y, sym_pairs, x_sym, spacing=1.0):
    device = x.device
    sym_loss = torch.tensor(0.0, device=device, dtype=torch.float32)
    num_constraints = 0
    if sym_pairs:
        i = torch.tensor([pair[0] for pair in sym_pairs], device=device)
        j = torch.tensor([pair[1] for pair in sym_pairs], device=device)
        xi = x[i]
        xj = x[j]
        yi = y[i]
        yj = y[j]
        x_sym_tensor = torch.tensor(x_sym, device=device, dtype=torch.float32)
        sym_loss += torch.sum((xi + xj - 2 * x_sym_tensor) ** 2)
        sym_loss += torch.sum((yi - yj) ** 2)
        num_constraints += len(sym_pairs)
    if num_constraints > 0:
        sym_loss /= num_constraints
    return sym_loss

def compute_oob_penalty(x, y, devices, X_L, X_H, Y_L, Y_H, gamma_oob, max_oob_penalty=1e6):
    """计算超出边界的惩罚，修复了标准化问题，并支持器件旋转"""
    device = x.device
    
    # 获取考虑旋转后的有效尺寸
    widths = []
    heights = []
    for dev in devices:
        eff_width, eff_height = get_device_dimensions(dev)
        widths.append(eff_width)
        heights.append(eff_height)
    
    widths = torch.tensor(widths, device=device, dtype=torch.float32)
    heights = torch.tensor(heights, device=device, dtype=torch.float32)
    
    # 不再进行标准化，使用原始尺寸
    
    left = x - widths / 2
    right = x + widths / 2
    bottom = y - heights / 2
    top = y + heights / 2
    
    # 计算OOB惩罚并限制最大值
    oob_penalty = torch.sum(torch.clamp(
        torch.log1p(torch.exp((X_L - left) / gamma_oob)) * gamma_oob, 
        max=max_oob_penalty
    ))
    oob_penalty += torch.sum(torch.clamp(
        torch.log1p(torch.exp((right - X_H) / gamma_oob)) * gamma_oob,
        max=max_oob_penalty
    ))
    oob_penalty += torch.sum(torch.clamp(
        torch.log1p(torch.exp((Y_L - bottom) / gamma_oob)) * gamma_oob,
        max=max_oob_penalty
    ))
    oob_penalty += torch.sum(torch.clamp(
        torch.log1p(torch.exp((top - Y_H) / gamma_oob)) * gamma_oob,
        max=max_oob_penalty
    ))
    return oob_penalty

def plot_layout(x, y, devices, sym_pairs, x_sym, logical_groups, title="Layout of Devices"):
    x = x.cpu().numpy() if isinstance(x, torch.Tensor) else x
    y = y.cpu().numpy() if isinstance(y, torch.Tensor) else y
    fig, ax = plt.subplots(figsize=(10, 10))
    
    # 为不同旋转角度设置不同颜色
    colors = {0: 'blue', 90: 'red'}
    
    for i, dev in enumerate(devices):
        xi, yi = x[i], y[i]
        
        # 获取考虑旋转后的有效尺寸
        wi, hi = get_device_dimensions(dev)
        rotation = dev.get('rotation', 0)
        
        # 选择颜色
        edge_color = colors.get(rotation, 'blue')
        
        rect = patches.Rectangle(
            (xi - wi / 2, yi - hi / 2), wi, hi, linewidth=1, 
            edgecolor=edge_color, facecolor='none',
            label=f'Devices ({rotation}度)' if i == 0 or (i == 1 and rotation != devices[0].get('rotation', 0)) else None
        )
        ax.add_patch(rect)
        
        # 显示器件名称和旋转角度
        rotation_text = f"\n({rotation}°)" if rotation != 0 else ""
        ax.text(xi + 0.1, yi, dev['name'] + rotation_text, fontsize=8, color='black')
    
    for i in range(len(devices)):
        for j in range(i + 1, len(devices)):
            xi, yi = x[i], y[i]
            xj, yj = x[j], y[j]
            
            # 获取考虑旋转后的有效尺寸
            wi, hi = get_device_dimensions(devices[i])
            wj, hj = get_device_dimensions(devices[j])
            
            left_i, right_i = xi - wi / 2, xi + wi / 2
            bottom_i, top_i = yi - hi / 2, yi + hi / 2
            left_j, right_j = xj - wj / 2, xj + wj / 2
            bottom_j, top_j = yj - hj / 2, yj + hj / 2
            overlap_width = min(right_i, right_j) - max(left_i, left_j)
            overlap_height = min(top_i, top_j) - max(bottom_i, bottom_j)
            if overlap_width > 0 and overlap_height > 0:
                overlap_left = max(left_i, left_j)
                overlap_bottom = max(bottom_i, bottom_j)
                rect = patches.Rectangle(
                    (overlap_left, overlap_bottom), overlap_width, overlap_height,
                    linewidth=0, facecolor='yellow', alpha=0.5, label='Overlap' if i == 0 and j == 1 else None
                )
                ax.add_patch(rect)
    
    y_min = min(y) - max(dev['height'] / 2 for dev in devices) - 1
    y_max = max(y) + max(dev['height'] / 2 for dev in devices) + 1
    x_min = min(x) - max(dev['width'] / 2 for dev in devices) - 1
    x_max = max(x) + max(dev['width'] / 2 for dev in devices) + 1
    
    if x_sym is not None and isinstance(x_sym, (int, float)):
        ax.axvline(x=x_sym, color='green', linestyle='--', label='Symmetry Axis')
    
    ax.set_xlabel('X Coordinate')
    ax.set_ylabel('Y Coordinate')
    ax.set_title(title)
    ax.legend()
    ax.set_aspect('equal')
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(y_min, y_max)
    plt.grid(False)
    plt.savefig(f'{title.replace(" ", "_").lower()}.png')
    plt.close()

def record_device_pins_table(x_final, y_final, devices, file_path=None):
    """
    打印或保存器件引脚坐标表格（包含MOS管的B极）。
    
    Parameters:
        x_final, y_final: 离散化后的中心坐标 (np.ndarray)
        devices: 设备列表（dicts）
        file_path: 若提供，则写入文件；否则打印到控制台
    """
    lines = []
    # 表头增加Bulk (B)列，保持对齐
    header = f"{'器件名称':<10} | {'Drain (D)':<12} | {'Gate (G)':<12} | {'Source (S)':<12} | {'Bulk (B)':<12} | {'类型'}"
    separator = "-" * len(header)
    lines.extend([header, separator])

    pins_list = generate_device_pins_for_astar(x_final, y_final, devices)

    for i, dev in enumerate(devices):
        name = dev['name']
        dev_type = dev['type']
        pins = pins_list[i]

        if dev_type == 'MOSFET':
            # MOS管有4个引脚：D、G、S、B
            d_str = str(pins[0])
            g_str = str(pins[1])
            s_str = str(pins[2])
            b_str = str(pins[3])  # 新增B极坐标
        elif dev_type == 'Resistor':
            # 电阻只有2个引脚，其他列留空
            d_str = str(pins[0])      # Pin1
            g_str = "—"               # 无栅极
            s_str = str(pins[1])      # Pin2
            b_str = "—"               # 无衬底
        else:
            # 未知器件类型，仅显示第一个引脚（如有）
            d_str = str(pins[0]) if len(pins) > 0 else "—"
            g_str = "—"
            s_str = "—"
            b_str = "—"

        # 行内容增加B极列
        line = f"{name:<10} | {d_str:<12} | {g_str:<12} | {s_str:<12} | {b_str:<12} | {dev_type}"
        lines.append(line)

    output = "\n".join(lines)
    
    if file_path:
        with open(file_path, 'w') as f:
            f.write(output)
        print(f"引脚坐标已保存到: {file_path}")
    else:
        print("器件引脚坐标（离散网格）:")
        print(output)

def record_device_corners(x_final, y_final, devices, file_path=None):
    """
    记录每个器件的四个直角坐标（左上角、右上角、右下角、左下角）
    
    Parameters:
        x_final, y_final: 离散化后的中心坐标 (np.ndarray)
        devices: 设备列表（dicts）
        file_path: 若提供，则写入文件；否则打印到控制台
    """
    lines = []
    header = f"{'器件名称':<10} | {'左上角':<15} | {'右上角':<15} | {'右下角':<15} | {'左下角':<15} | {'旋转角度'}"
    separator = "-" * len(header)
    lines.extend([header, separator])

    for i, dev in enumerate(devices):
        name = dev['name']
        cx, cy = int(round(x_final[i])), int(round(y_final[i]))
        
        # 获取考虑旋转后的有效尺寸
        eff_width, eff_height = get_device_dimensions(dev)
        w, h = int(round(eff_width)), int(round(eff_height))
        rotation = dev.get('rotation', 0)
        
        # 计算四个角的坐标
        half_w, half_h = w // 2, h // 2
        
        # 左上角
        top_left = (cx - half_w, cy + half_h)
        # 右上角
        top_right = (cx + half_w, cy + half_h)
        # 右下角
        bottom_right = (cx + half_w, cy - half_h)
        # 左下角
        bottom_left = (cx - half_w, cy - half_h)
        
        # 格式化输出
        line = f"{name:<10} | {str(top_left):<15} | {str(top_right):<15} | {str(bottom_right):<15} | {str(bottom_left):<15} | {rotation}°"
        lines.append(line)

    output = "\n".join(lines)
    
    if file_path:
        with open(file_path, 'w') as f:
            f.write(output)
        print(f"器件四角坐标已保存到: {file_path}")
    else:
        print("器件四角坐标（离散网格）:")
        print(output)


import numpy as np
from typing import List, Tuple

def discretize_and_fix_overlap(
    x: np.ndarray,
    y: np.ndarray,
    devices: List,
    min_spacing: int = 0,
    max_attempts: int = 1000
) -> Tuple[np.ndarray, np.ndarray]:
    """
    修复离散化后设备矩形之间的重叠。

    参数:
        x, y: 离散化后的整数坐标数组（设备左下角）。
        devices: 设备列表，每个元素需有 .width 和 .height 属性（或字典键）。
        min_spacing: 设备间最小间距（默认0，即允许紧贴）。
        max_attempts: 随机扰动最大尝试次数（防死循环）。

    返回:
        修复后的 x, y（numpy arrays）
    """
    n = len(x)
    x_fixed = x.copy()
    y_fixed = y.copy()

    # 构建矩形列表 [(x, y, w, h), ...]
    rects = []
    for i in range(n):
        w = getattr(devices[i], 'width', devices[i].get('width', 1))
        h = getattr(devices[i], 'height', devices[i].get('height', 1))
        rects.append((x_fixed[i], y_fixed[i], w, h))

    def overlap(r1, r2):
        x1, y1, w1, h1 = r1
        x2, y2, w2, h2 = r2
        return not (x1 + w1 + min_spacing <= x2 or
                    x2 + w2 + min_spacing <= x1 or
                    y1 + h1 + min_spacing <= y2 or
                    y2 + h2 + min_spacing <= y1)

    # 简单贪心 + 随机扰动策略
    for i in range(n):
        attempts = 0
        while attempts < max_attempts:
            has_overlap = False
            for j in range(i):
                if overlap(rects[i], rects[j]):
                    has_overlap = True
                    break
            if not has_overlap:
                break

            # 有重叠：随机扰动当前设备位置（小范围）
            dx = np.random.randint(-2, 3)  # -2 to 2
            dy = np.random.randint(-2, 3)
            x_fixed[i] += dx
            y_fixed[i] += dy
            # 更新 rects[i]
            w = getattr(devices[i], 'width', devices[i].get('width', 1))
            h = getattr(devices[i], 'height', devices[i].get('height', 1))
            rects[i] = (x_fixed[i], y_fixed[i], w, h)
            attempts += 1

        if attempts == max_attempts:
            print(f"Warning: Device {i} still overlaps after {max_attempts} attempts.")

    return x_fixed, y_fixed


import numpy as np
from typing import List, Tuple, Any

import numpy as np
from typing import List, Dict, Tuple

def generate_device_pins_for_astar(
    x: np.ndarray,
    y: np.ndarray,
    devices: List[Dict]
) -> List[List[Tuple[int, int]]]:
    """
    生成 A* 布线所需的引脚坐标，严格按端口顺序：
        - MOSFET: [Drain, Gate, Source, Bulk]
        - Resistor: [Pin1, Pin2] （左、右）

    Parameters:
        x, y: 离散化后的中心坐标（numpy arrays）
        devices: list of device dicts with 'type', 'width', 'height'

    Returns:
        List[List[(x, y)]]: 每个器件的引脚坐标列表
    """
    pins = []
    for i in range(len(x)):
        cx = int(round(x[i]))
        cy = int(round(y[i]))
        dev = devices[i]

        dev_type = dev['type']
        w = dev['width']
        h = dev['height']

        if dev_type == 'MOSFET':
            w_int = int(round(w))
            h_int = int(round(h))
            
            # Drain: 右边缘中心
            drain_x = cx + w_int // 2
            drain = (drain_x, cy)
            
            # Gate: 上边缘中心
            gate_y = cy + h_int // 2
            gate = (cx, gate_y)
            
            # Source: 左边缘中心
            source_x = cx - w_int // 2
            source = (source_x, cy)
            
            # Bulk: 下边缘中心（通常与源极同侧或底部，这里按底部中心处理）
            bulk_y = cy - h_int // 2
            bulk = (cx, bulk_y)
            
            # 严格按照 D, G, S, B 顺序
            pin_list = [drain, gate, source, bulk]

        elif dev_type == 'Resistor':
            w_int = int(round(w))
            # 假设横向放置，Pin1=左，Pin2=右
            pin1 = (cx - w_int // 2, cy)
            pin2 = (cx + w_int // 2, cy)
            pin_list = [pin1, pin2]

        else:
            pin_list = [(cx, cy)]
            print(f"Warning: Unknown device type '{dev_type}', using center pin.")

        # 确保整数坐标
        pin_list = [(int(px), int(py)) for px, py in pin_list]
        pins.append(pin_list)

    return pins
def resolve_overlap_greedy_with_symmetry(x_final, y_final, devices, sym_pairs, x_sym=0.0, max_iter=1000, min_gap=0.0):
    """
    贪心推开重叠，同时尽量保持对称性。
    
    参数:
        x_final, y_final: 初始坐标 (np.ndarray)
        devices: 器件列表
        sym_pairs: 对称对索引列表，如 [(0,1), (2,3)]
        x_sym: 对称轴 x 坐标（默认 0.0）
        max_iter: 最大迭代次数
        min_gap: 最小间距（可为 0）
    
    返回:
        修复后的 x, y (float array)
    """
    x = x_final.astype(float).copy()
    y = y_final.astype(float).copy()
    n = len(devices)
    
    # 构建对称映射
    sym_map = {}
    for i, j in sym_pairs:
        sym_map[i] = j
        sym_map[j] = i

    # 预计算有效宽高（考虑旋转）
    eff_w = []
    eff_h = []
    for dev in devices:
        w, h = dev['width'], dev['height']
        if dev.get('rotation', 0) == 90:
            w, h = h, w
        eff_w.append(w)
        eff_h.append(h)
    eff_w = np.array(eff_w)
    eff_h = np.array(eff_h)

    for it in range(max_iter):
        overlap_found = False

        for i in range(n):
            for j in range(i + 1, n):
                # 计算边界
                l1 = x[i] - eff_w[i] / 2
                r1 = x[i] + eff_w[i] / 2
                b1 = y[i] - eff_h[i] / 2
                t1 = y[i] + eff_h[i] / 2

                l2 = x[j] - eff_w[j] / 2
                r2 = x[j] + eff_w[j] / 2
                b2 = y[j] - eff_h[j] / 2
                t2 = y[j] + eff_h[j] / 2

                overlap_x = max(0.0, min(r1, r2) - max(l1, l2))
                overlap_y = max(0.0, min(t1, t2) - max(b1, b2))
                if overlap_x * overlap_y <= 1e-9:
                    continue

                overlap_found = True

                # === 判断是否涉及对称对 ===
                i_in_sym = i in sym_map
                j_in_sym = j in sym_map
                is_sym_pair = (i_in_sym and sym_map[i] == j)

                if is_sym_pair:
                    # 情况1: 对称对内部重叠（不应发生，但万一）
                    # 强制它们 y 相同，x 关于 x_sym 对称，并沿 Y 方向推开
                    mid_x = x_sym
                    avg_y = (y[i] + y[j]) / 2
                    # 沿 Y 方向拉开
                    required_h = (eff_h[i] + eff_h[j]) / 2 + min_gap
                    current_dy = abs(y[i] - y[j])
                    if current_dy < required_h:
                        dy = (required_h - current_dy) / 2
                        y[i] = avg_y - dy
                        y[j] = avg_y + dy
                    # 修正 x 严格对称
                    x[i] = mid_x - (x[j] - mid_x)
                    # 或者：x[i] = 2 * mid_x - x[j]

                elif i_in_sym or j_in_sym:
                    # 情况2: 一个在对称对中，另一个不在
                    # 移动非对称器件，或对称地移动整个对
                    if i_in_sym:
                        sym_i = sym_map[i]
                        # 尝试移动 j（非对称方）
                        # 或者：将 (i, sym_i) 整体移动，保持对称
                        # 这里选择：优先移动非对称器件 j
                        _push_single_device(i, j, x, y, eff_w, eff_h, min_gap)
                    else:
                        sym_j = sym_map[j]
                        _push_single_device(j, i, x, y, eff_w, eff_h, min_gap)

                else:
                    # 情况3: 两个都不在对称对中 → 普通推开
                    _push_pair_devices(i, j, x, y, eff_w, eff_h, min_gap)

        if not overlap_found:
            break

        if it == max_iter - 1:
            print(f"⚠️ 贪心对称修复达到最大迭代 {max_iter}")

    # === 最后：强制对称对严格对称（微调）===
    for i, j in sym_pairs:
        avg_y = (y[i] + y[j]) / 2
        y[i] = y[j] = avg_y
        mid_x = x_sym
        # 保持 x[i] 和 x[j] 关于 mid_x 对称
        center = (x[i] + x[j]) / 2
        offset = center - mid_x
        x[i] = x[i] - offset
        x[j] = x[j] - offset

    return x, y


def _push_single_device(sym_idx, other_idx, x, y, eff_w, eff_h, min_gap):
    """推动非对称器件，避免破坏对称器件的位置"""
    i, j = sym_idx, other_idx
    # 计算最小推开距离
    push_x = (eff_w[i] + eff_w[j]) / 2 + min_gap - abs(x[i] - x[j])
    push_y = (eff_h[i] + eff_h[j]) / 2 + min_gap - abs(y[i] - y[j])
    push_x = max(0.0, push_x)
    push_y = max(0.0, push_y)

    if push_x >= push_y and push_x > 1e-6:
        dx = x[j] - x[i]
        if dx >= 0:
            x[j] += push_x
        else:
            x[j] -= push_x
    elif push_y > 1e-6:
        dy = y[j] - y[i]
        if dy >= 0:
            y[j] += push_y
        else:
            y[j] -= push_y


def _push_pair_devices(i, j, x, y, eff_w, eff_h, min_gap):
    """普通推开（非对称器件）"""
    push_x = (eff_w[i] + eff_w[j]) / 2 + min_gap - abs(x[i] - x[j])
    push_y = (eff_h[i] + eff_h[j]) / 2 + min_gap - abs(y[i] - y[j])
    push_x = max(0.0, push_x)
    push_y = max(0.0, push_y)

    if push_x >= push_y and push_x > 1e-6:
        dx = x[j] - x[i]
        if dx >= 0:
            x[i] -= push_x / 2
            x[j] += push_x / 2
        else:
            x[i] += push_x / 2
            x[j] -= push_x / 2
    elif push_y > 1e-6:
        dy = y[j] - y[i]
        if dy >= 0:
            y[i] -= push_y / 2
            y[j] += push_y / 2
        else:
            y[i] += push_y / 2
            y[j] -= push_y / 2


def infer_symmetric_pairs(devices, size_tolerance=1e-3, existing_sym_pairs=None):
    """
    根据器件尺寸自动推断对称对。
    
    参数:
        devices: list of dict, 每个含 'width', 'height'
        size_tolerance: 尺寸容差（绝对值），如 0.5 表示允许 0.5 单位差异
        existing_sym_pairs: 已有的对称对（set of frozenset({i,j})），避免重复
    
    返回:
        inferred_pairs: list of (i, j)
    """
    if existing_sym_pairs is None:
        existing = set()
    else:
        existing = {frozenset(pair) for pair in existing_sym_pairs}
    
    n = len(devices)
    inferred = []
    matched = [False] * n  # 防止一个器件匹配多个（可选）

    for i in range(n):
        if matched[i]:
            continue
        size_i = tuple(sorted([devices[i]['width'], devices[i]['height']]))
        for j in range(i + 1, n):
            if matched[j] or frozenset([i, j]) in existing:
                continue
            size_j = tuple(sorted([devices[j]['width'], devices[j]['height']]))
            # 比较两个尺寸是否在容差内
            if (abs(size_i[0] - size_j[0]) <= size_tolerance and
                abs(size_i[1] - size_j[1]) <= size_tolerance):
                inferred.append((i, j))
                matched[i] = True
                matched[j] = True
                break  # 每个器件只匹配一个（贪心）
    
    return inferred




def optimize_layout(netlist_content, target_area=200.0, max_steps=5000):
    # 解析网表内容
    devices, nets, device_name_to_index, logical_groups = parse_spice_netlist(netlist_content, multi=True)
    print('********************device*******************************')
    print(devices)
    print('********************device*******************************')
    if not devices:
        print("警告：没有从网表中解析到任何器件！")
        return None, None
    
    sym_pairs, x_sym = [], 0.0  # 示例中未涉及对称约束
    # === 自动推断额外的对称对 ===
    auto_sym_pairs = infer_symmetric_pairs(
    devices,
    size_tolerance=0.5,           # 根据你的单位调整
    existing_sym_pairs=sym_pairs  # 避免重复
)
    # 合并
    sym_pairs = sym_pairs + auto_sym_pairs

    print(f"自动推断出 {len(auto_sym_pairs)} 对对称器件")
    # 调整参数，避免数值溢出
    params = {
        'n_devices': len(devices),
        'nets': nets,
        'sym_pairs': sym_pairs,
        'logical_groups': logical_groups,
        'beta_hpwl_initial': 5.0,
        'beta_hpwl_final': 1.0,
        'lambda_overlap_base': 1000.0,
        'lambda_overlap_max': 10000.0,
        'lambda_overlap_min': 800.0,
        'lambda_oob': 5.0,
        'tau_sym_initial': 5000,
        'tau_sym_max': 20000.0,
        'eta': 0.03,
        'eta_sym_factor': 10.0,
        'alpha_lse': 0.1,
        'gamma_oob': 0.5,
        'lr': 0.05,
        'max_steps': max_steps,
        'min_steps': 50,
        'density_factor': 5.0,
        'x_sym': x_sym,
        'spacing': 1.0,
        'overlap_power': 2,
        'overlap_sensitivity': 0.05,
        'max_overlap_penalty': 1e6,
        'max_oob_penalty': 1e5
    }

    # 计算实际总面积并进行缩放
    actual_total_area = sum(dev['width'] * dev['height'] for dev in devices)
    scale = (target_area / actual_total_area) ** 0.5 if actual_total_area > 0 else 1.0
    for dev in devices:
        dev['width'] *= scale
        dev['height'] *= scale

    total_device_area = sum(dev['width'] * dev['height'] for dev in devices)

    side = np.sqrt(target_area * params['density_factor'])
    X_L = torch.tensor(-side / 2, device=device, dtype=torch.float32)
    X_H = torch.tensor(side / 2, device=device, dtype=torch.float32)
    Y_L = torch.tensor(-side / 2, device=device, dtype=torch.float32)
    Y_H = torch.tensor(side / 2, device=device, dtype=torch.float32)

    num_devices = len(devices)
    x = torch.randn(num_devices, device=device) * (side / 6)
    y = torch.randn(num_devices, device=device) * (side / 6)

    T_initial = 3000.0
    alpha = 0.95
    T_min = 0.01
    num_perturbations = 100 * num_devices
    delta_x = 0.1 * (X_H - X_L)
    delta_y = 0.1 * (Y_H - Y_L)

    beta_hpwl = params['beta_hpwl_initial']
    lambda_overlap = params['lambda_overlap_base']
    tau_sym = params['tau_sym_initial']
    lambda_oob = params['lambda_oob']

    start_time = time.time()
    print("初始布局:")
    
    # 在初始布局时检查重叠情况
    initial_overlap_penalty, initial_overlap_area = compute_overlap(x, y, devices, overlap_power=params['overlap_power'], debug=False)
    print(f"初始重叠面积: {initial_overlap_area.item():.6f}")
    
    plot_layout(x, y, devices, sym_pairs, x_sym, logical_groups, title="Initial Device Layout")

    T = T_initial
    iteration = 0

    # ===== 新增：用于面积收敛判断 =====
    best_bb_area = float('inf')
    no_improve_count = 0
    patience = 100  # 连续20次无改善则停止
    min_overlap_threshold = 1e-4  # 几乎无重叠

    while T > T_min and iteration < params['max_steps']:
        # 在外层循环开始时计算当前状态的各项指标
        hpwl = compute_hpwl(x, y, nets, devices, params['alpha_lse'])
        overlap_penalty, overlap_area = compute_overlap(
            x, y, devices, 
            overlap_power=params['overlap_power'],
            max_overlap_penalty=params['max_overlap_penalty']
        )
        sym = compute_symmetry(x, y, sym_pairs, x_sym, params['spacing'])
        oob_penalty = compute_oob_penalty(
            x, y, devices, X_L, X_H, Y_L, Y_H, 
            params['gamma_oob'],
            max_oob_penalty=params['max_oob_penalty']
        )
        
        for _ in range(num_perturbations):
            idx = torch.randint(0, num_devices, (1,), device=device).item()
            
            # 决定操作类型：位置移动或旋转
            operation_type = torch.rand((), device=device).item()
            
            # 创建新状态的副本
            x_new = x.clone()
            y_new = y.clone()
            devices_new = [dev.copy() for dev in devices]  # 深拷贝器件列表
            
            if operation_type < 1.0:  # 80%概率进行位置移动
                dx = (torch.rand((), device=device) * 2 - 1) * delta_x
                dy = (torch.rand((), device=device) * 2 - 1) * delta_y
                x_new[idx] += dx
                y_new[idx] += dy
            else:  # 20%概率进行旋转
                current_rotation = devices[idx].get('rotation', 0)
                devices_new[idx]['rotation'] = 90 if current_rotation == 0 else 0

            # 跳过无效解
            if torch.isinf(hpwl) or torch.isinf(overlap_penalty) or torch.isinf(oob_penalty):
                continue
                    
            loss_current = (beta_hpwl * hpwl +
                        lambda_overlap * overlap_penalty +
                        tau_sym * sym +
                        lambda_oob * oob_penalty)

            hpwl_new = compute_hpwl(x_new, y_new, nets, devices_new, params['alpha_lse'])
            overlap_penalty_new, overlap_area_new = compute_overlap(
                x_new, y_new, devices_new,
                overlap_power=params['overlap_power'],
                max_overlap_penalty=params['max_overlap_penalty']
            )
            sym_new = compute_symmetry(x_new, y_new, sym_pairs, x_sym, params['spacing'])
            oob_penalty_new = compute_oob_penalty(
                x_new, y_new, devices_new, X_L, X_H, Y_L, Y_H,
                params['gamma_oob'],
                max_oob_penalty=params['max_oob_penalty']
            )
            
            if torch.isinf(hpwl_new) or torch.isinf(overlap_penalty_new) or torch.isinf(oob_penalty_new):
                continue
                
            loss_new = (beta_hpwl * hpwl_new +
                       lambda_overlap * overlap_penalty_new +
                       tau_sym * sym_new +
                       lambda_oob * oob_penalty_new)

            delta_loss = loss_new - loss_current
            if not torch.isnan(delta_loss) and (delta_loss <= 0 or 
                    torch.rand(1, device=device).item() < math.exp(-delta_loss.item() / T)):
                x = x_new
                y = y_new
                devices = devices_new
                hpwl = hpwl_new
                overlap_penalty = overlap_penalty_new
                overlap_area = overlap_area_new
                sym = sym_new
                oob_penalty = oob_penalty_new

        overlap_percentage = (overlap_area.item() / total_device_area) * 100 if total_device_area > 0 else 0
        if overlap_percentage < params['overlap_sensitivity'] * 100:
            lambda_overlap = params['lambda_overlap_min']
            eta_sym = params['eta'] * params['eta_sym_factor']
        else:
            lambda_overlap += params['eta'] * overlap_penalty.item()
            lambda_overlap = min(lambda_overlap, params['lambda_overlap_max'])
            eta_sym = params['eta']
        
        tau_sym += eta_sym * sym.item()
        tau_sym = min(tau_sym, params['tau_sym_max'])
        lambda_oob += params['eta'] * oob_penalty.item()
        lambda_oob = min(lambda_oob, 100.0)

        average_width = np.mean([dev['width'] for dev in devices]) if devices else 1.0
        average_height = np.mean([dev['height'] for dev in devices]) if devices else 1.0
        rms_x = torch.tensor(0.0, device=device)
        rms_y = torch.tensor(0.0, device=device)
        if params['sym_pairs']:
            sym_dev_x = [x[i] + x[j] - 2 * params['x_sym'] for i, j in params['sym_pairs']]
            rms_x = torch.sqrt(torch.mean(torch.tensor([d ** 2 for d in sym_dev_x], device=device)))
            sym_dev_y = [y[i] - y[j] for i, j in params['sym_pairs']]
            rms_y = torch.sqrt(torch.mean(torch.tensor([d ** 2 for d in sym_dev_y], device=device)))

        # ===== 计算当前包围盒面积（考虑旋转） =====
        x_coords = x.detach().cpu().numpy()
        y_coords = y.detach().cpu().numpy()
        widths = np.array([dev['width'] for dev in devices])
        heights = np.array([dev['height'] for dev in devices])
        rotations = np.array([dev.get('rotation', 0) for dev in devices])

        # 旋转90度时宽高互换
        effective_widths = np.where(rotations == 90, heights, widths)
        effective_heights = np.where(rotations == 90, widths, heights)

        left = x_coords - effective_widths / 2
        right = x_coords + effective_widths / 2
        bottom = y_coords - effective_heights / 2
        top = y_coords + effective_heights / 2

        bb_width = np.max(right) - np.min(left)
        bb_height = np.max(top) - np.min(bottom)
        current_bb_area = bb_width * bb_height

        # 更新最佳包围盒面积
        if current_bb_area < best_bb_area - 1e-3:
            best_bb_area = current_bb_area
            no_improve_count = 0
        else:
            no_improve_count += 1

        if iteration % 10 == 0:
            loss = (beta_hpwl * hpwl +
                   lambda_overlap * overlap_penalty +
                   tau_sym * sym +
                   lambda_oob * oob_penalty +1.0 * best_bb_area)
            
            if torch.isinf(loss) or torch.isnan(loss):
                print(f"迭代 {iteration}: 检测到无效损失值，重置权重")
                lambda_overlap = params['lambda_overlap_base']
                tau_sym = params['tau_sym_initial']
                lambda_oob = params['lambda_oob']
                continue
                
            print(
                f"迭代 {iteration}, 温度: {T:.4f}, 损失: {loss.item():.4f}, HPWL: {hpwl.item():.4f}, "
                f"重叠: {overlap_area.item():.4f} ({overlap_percentage:.2f}%), "
                f"包围盒面积: {current_bb_area:.4f}, "
                f"对称惩罚: {sym.item():.4f}, OOB 惩罚: {oob_penalty.item():.4f}, "
                f"RMS_x: {rms_x.item():.4f}, RMS_y: {rms_y.item():.4f}, "
                f"权重: beta_hpwl={beta_hpwl:.2f}, lambda_overlap={lambda_overlap:.2f}, "
                f"tau_sym={tau_sym:.2f}, lambda_oob={lambda_oob:.2f}, "
                f"当前包围盒面积: {current_bb_area:.4f}, 最佳包围盒面积: {best_bb_area:.4f}")
                        
            if iteration == 0:
                actual_overlap_penalty, actual_overlap_area = compute_overlap(
                    x, y, devices, 
                    overlap_power=params['overlap_power'],
                    max_overlap_penalty=params['max_overlap_penalty']
                )
                print(f"  -> 实际重叠面积: {actual_overlap_area.item():.6f} (用于验证)")
            
            rotation_stats = {}
            for dev in devices:
                rot = dev.get('rotation', 0)
                rotation_stats[rot] = rotation_stats.get(rot, 0) + 1
            rotation_info = ", ".join([f"{deg}°: {count}个" for deg, count in sorted(rotation_stats.items())])
            print(f"  -> 旋转统计: {rotation_info}")

        # ===== 新的终止条件：无重叠 + 包围盒收敛 +（可选）对称性满足 =====
        sym_ok = (not params['sym_pairs']) or (rms_x.item() <= 0.01 * average_width and rms_y.item() <= 0.01 * average_height)
        
        if (iteration >= params['min_steps'] and 
            overlap_area.item() <= min_overlap_threshold and 
            sym_ok and
            no_improve_count >= patience):
            print(f"在迭代 {iteration} 停止: 无重叠、对称性满足，且包围盒面积连续 {patience} 次未改善。")
            print(f"最终包围盒面积: {current_bb_area:.4f}, 器件总面积: {total_device_area:.4f}")
            break

        T *= alpha
        iteration += 1

    end_time = time.time()
    print(f"总优化时间: {end_time - start_time:.2f} 秒")
    print("最终布局:")
    print("Final coordinates:", torch.stack([x, y], dim=1).cpu().numpy())
    x_final = np.round(x.cpu().numpy()).astype(int)
    y_final = np.round(y.cpu().numpy()).astype(int)
    x_final, y_final = discretize_and_fix_overlap(x_final, y_final, devices, min_spacing=0)
    def check_overlap_final(x, y, devices):
        n = len(devices)
        total = 0.0
        rects = []
        for i in range(n):
            w = devices[i]['width']
            h = devices[i]['height']
            if devices[i].get('rotation', 0) == 90:
                w, h = h, w
            cx, cy = x[i], y[i]
            rects.append((cx - w/2, cx + w/2, cy - h/2, cy + h/2))
        for i in range(n):
            for j in range(i+1, n):
                l1, r1, b1, t1 = rects[i]
                l2, r2, b2, t2 = rects[j]
                ox = max(0.0, min(r1, r2) - max(l1, l2))
                oy = max(0.0, min(t1, t2) - max(b1, b2))
                total += ox * oy
        return total > 1e-6, total

    has_overlap, overlap_area = check_overlap_final(x_final, y_final, devices)
    if has_overlap:
        print(f"⚠️ 初始最终布局存在重叠 ({overlap_area:.6f})，启动贪心推开算法...")
        x_final, y_final = resolve_overlap_greedy_with_symmetry(
        x_final, y_final, devices,
        sym_pairs=sym_pairs,      # ← 传入对称对
        x_sym=x_sym,              # ← 传入对称轴
        max_iter=500,
        min_gap=0.0
    )
        # 再次验证
        has_overlap2, overlap_area2 = check_overlap_final(x_final, y_final, devices)
        if has_overlap2:
            print(f"❌ 贪心修复后仍有重叠: {overlap_area2:.6f}")
            # 可选择 raise 或继续
        else:
            print("✅ 贪心修复成功，最终布局无重叠。")
    # ✅ 生成 A* 可用的引脚坐标
    device_pins = generate_device_pins_for_astar(x_final, y_final, devices)
    record_device_pins_table(x_final, y_final, devices, "./cache/auto_placement/placement.txt")
    record_device_corners(x_final, y_final, devices, "./cache/auto_placement/placement_full.txt")
    plot_layout(x_final, y_final, devices, sym_pairs, x_sym, logical_groups, title="Final Device Layout")
    return {
        'x': x_final,
        'y': y_final,
        'pins': device_pins,      # List[List[(x,y)]]
        'devices': devices
    }

if __name__ == "__main__":
    # 输入SPICE网表
    spice_netlist = """.title Img_cicuit
.lib /path/to/pdk/sky130.lib.spice tt
VVDD_supply VDD 0 3.3V
Vinput_1 Vin1 0 dc=1.6@u_V, ac=0.5@u_V
Vinput_2 Vin2 0 dc=1.6@u_V, ac=-0.5@u_V
Vbias_1 Vb 0 1.1V
XM1 Vout1 Vin1 Node_mid 0 sky130_fd_pr__nfet_01v8 l=1.2 mult=1 nf=1 w=9.600000000000001
XM2 Vout2 Vin2 Node_mid 0 sky130_fd_pr__nfet_01v8 l=2.2 mult=1 nf=1 w=7.4
XM3 Vout1 Node_mid VDD VDD sky130_fd_pr__pfet_01v8 l=4.1000000000000005 mult=1 nf=1 w=5.800000000000001
XM4 Vout2 Node_mid VDD VDD sky130_fd_pr__pfet_01v8 l=2.0 mult=1 nf=1 w=3.4000000000000004
XM5 Node_mid Vb 0 0 sky130_fd_pr__nfet_01v8 l=1.3 mult=1 nf=1 w=9.2
RR1 Vout1 Node_mid 20000.0Ohm
RR2 Vout2 Node_mid 20000.0Ohm


"""
    optimize_layout(spice_netlist)
    