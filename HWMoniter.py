# --- PyInstaller DLL Path Fix ---
import os
import sys
if getattr(sys, 'frozen', False):
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
# --- End of Fix ---

import sys
import os
import glfw
import OpenGL.GL as gl
import imgui
from imgui.integrations.glfw import GlfwRenderer
import psutil
import pynvml
import math
import time
import re

# --- NVML (GPU) Wrapper ---
nvml_initialized = False

def init_nvml():
    """NVML을 초기화하고 첫 번째 GPU 핸들을 반환합니다."""
    global nvml_initialized
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        nvml_initialized = True
        print("NVML 초기화 성공.")
        return handle
    except pynvml.NVMLError as error:
        print(f"NVML 초기화 오류: {error}", file=sys.stderr)
        print("NVIDIA 드라이버가 설치되어 있는지 확인하세요. GPU 모니터링이 비활성화됩니다.", file=sys.stderr)
        return None

def get_gpu_usage(handle):
    """주어진 핸들로 GPU 코어 사용률을 가져옵니다."""
    if handle is None:
        return 0
    try:
        return pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
    except pynvml.NVMLError:
        return 0

def get_gpu_memory_usage(handle):
    """GPU 메모리(VRAM) 사용 정보를 반환합니다. (퍼센트, 사용량 MB, 총량 MB)"""
    if handle is None:
        return 0, 0, 0
    try:
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        percent = (info.used / info.total) * 100
        used_mb = info.used / (1024**2)
        total_mb = info.total / (1024**2)
        return percent, used_mb, total_mb
    except pynvml.NVMLError:
        return 0, 0, 0

# --- System Info Functions ---
def get_ram_usage():
    """메인 메모리(RAM) 사용 정보를 반환합니다. (퍼센트, 사용량 GB, 총량 GB)"""
    mem_info = psutil.virtual_memory()
    percent = mem_info.percent
    used_gb = mem_info.used / (1024**3)
    total_gb = mem_info.total / (1024**3)
    return percent, used_gb, total_gb

def get_disk_info(drive_letter):
    """지정된 드라이브의 디스크 정보를 반환합니다. (퍼센트, 사용량 GB, 총량 GB)"""
    try:
        usage = psutil.disk_usage(f'{drive_letter}:\\')
        return {
            'percent': usage.percent,
            'used_gb': usage.used / (1024**3),
            'total_gb': usage.total / (1024**3)
        }
    except FileNotFoundError:
        return None


def get_network_speed_mbps():

    """가장 활성화된 네트워크 인터페이스의 링크 속도를 Mbps 단위로 가져옵니다."""
    try:
        stats = psutil.net_if_stats()
        io_counters = psutil.net_io_counters(pernic=True)

        best_interface_speed = 0
        max_bytes = 0

        for nic, addrs in psutil.net_if_addrs().items():
            if nic in stats and stats[nic].isup:
                if nic in io_counters and (io_counters[nic].bytes_sent + io_counters[nic].bytes_recv) > max_bytes:
                    if stats[nic].speed > 0:
                        max_bytes = io_counters[nic].bytes_sent + io_counters[nic].bytes_recv
                        best_interface_speed = stats[nic].speed
        
        return best_interface_speed if best_interface_speed > 0 else 100
    except Exception:
        return 100

# --- Drawing Functions ---
def get_gradient_color(value):
    """0-100 값에 따라 Green-Yellow-Red 그라데이션 색상을 계산하여 (R,G,B,A) 튜플로 반환합니다."""
    value = min(max(value, 0), 100)
    if value <= 50:
        r = (value * 2) / 100.0
        g = 1.0
    else:
        r = 1.0
        g = 1.0 - ((value - 50) * 2) / 100.0
    return (r, g, 0, 1.0)

def draw_combined_gauge(draw_list, center, radius, outer_percent, inner_percent, label, sub_text=None):
    """외부 링과 내부 원으로 구성된 결합된 게이지를 그립니다."""
    background_thickness = 8
    foreground_thickness = 12
    
    outer_color = get_gradient_color(outer_percent)
    main_outer_color = imgui.get_color_u32_rgba(*outer_color)
    draw_list.add_circle(center.x, center.y, radius, imgui.get_color_u32_rgba(0.2, 0.2, 0.2, 1.0), num_segments=128, thickness=background_thickness)
    if outer_percent > 0:
        angle_start = -math.pi / 2
        angle_end = angle_start + (min(outer_percent, 100) / 100.0) * (2 * math.pi)
        num_segments = int(128 * min(outer_percent, 100) / 100)
        if num_segments < 2: num_segments = 2
        draw_list.path_clear()
        draw_list.path_arc_to(center.x, center.y, radius, angle_start, angle_end, num_segments=num_segments)
        draw_list.path_stroke(main_outer_color, thickness=foreground_thickness)

    if inner_percent > 0:
        inner_color = get_gradient_color(inner_percent)
        main_inner_color = imgui.get_color_u32_rgba(inner_color[0], inner_color[1], inner_color[2], 0.6)
        inner_radius = radius * (inner_percent / 100.0)
        draw_list.add_circle_filled(center.x, center.y, inner_radius, main_inner_color, num_segments=128)

    text = f"{int(outer_percent)}%"
    text_size = imgui.calc_text_size(text)
    text_pos = imgui.Vec2(center.x - text_size.x / 2, center.y - text_size.y / 2)
    draw_list.add_text(text_pos.x, text_pos.y, imgui.get_color_u32_rgba(1, 1, 1, 1), text)

    label_size = imgui.calc_text_size(label)
    label_pos = imgui.Vec2(center.x - label_size.x / 2, center.y + radius + 15)
    draw_list.add_text(label_pos.x, label_pos.y, imgui.get_color_u32_rgba(0.8, 0.8, 0.8, 1), label)

    if sub_text:
        sub_text_size = imgui.calc_text_size(sub_text)
        sub_text_pos = imgui.Vec2(center.x - sub_text_size.x / 2, label_pos.y + label_size.y + 5)
        draw_list.add_text(sub_text_pos.x, sub_text_pos.y, imgui.get_color_u32_rgba(0.7, 0.7, 0.7, 1), sub_text)

def draw_network_gauge(draw_list, center, radius, upload_percent, download_percent, label, upload_speed_mbps, download_speed_mbps):
    """Upload/Download를 함께 표시하는 네트워크 게이지를 그립니다."""
    background_thickness = 8
    foreground_thickness = 12

    color_percent = (upload_percent + download_percent) / 2.0
    r, g, b, a = get_gradient_color(color_percent)
    main_color = imgui.get_color_u32_rgba(r, g, b, a)

    draw_list.add_circle(
        center.x, center.y, radius, imgui.get_color_u32_rgba(0.2, 0.2, 0.2, 1.0),
        num_segments=128, thickness=background_thickness
    )

    if upload_percent > 0:
        angle_end_up = -math.pi / 2
        angle_start_up = angle_end_up - (min(upload_percent, 100) / 100.0) * math.pi
        num_segments = int(64 * min(upload_percent, 100) / 100)
        if num_segments < 2: num_segments = 2
        draw_list.path_clear()
        draw_list.path_arc_to(center.x, center.y, radius, angle_start_up, angle_end_up, num_segments=num_segments)
        draw_list.path_stroke(main_color, thickness=foreground_thickness)

    if download_percent > 0:
        angle_start_down = -math.pi / 2
        angle_end_down = angle_start_down + (min(download_percent, 100) / 100.0) * math.pi
        num_segments = int(64 * min(download_percent, 100) / 100)
        if num_segments < 2: num_segments = 2
        draw_list.path_clear()
        draw_list.path_arc_to(center.x, center.y, radius, angle_start_down, angle_end_down, num_segments=num_segments)
        draw_list.path_stroke(main_color, thickness=foreground_thickness)

    label_size = imgui.calc_text_size(label)
    label_pos = imgui.Vec2(center.x - label_size.x / 2, center.y + radius + 15)
    draw_list.add_text(label_pos.x, label_pos.y, imgui.get_color_u32_rgba(0.8, 0.8, 0.8, 1), label)

    up_text = f"U: {upload_speed_mbps:.1f}"
    down_text = f"D: {download_speed_mbps:.1f}"

    up_text_size = imgui.calc_text_size(up_text)
    down_text_size = imgui.calc_text_size(down_text)

    text_padding = 5
    total_height = up_text_size.y + down_text_size.y + text_padding
    
    up_pos_y = center.y - total_height / 2
    down_pos_y = up_pos_y + up_text_size.y + text_padding

    up_pos_x = center.x - up_text_size.x / 2
    down_pos_x = center.x - down_text_size.x / 2

    draw_list.add_text(up_pos_x, up_pos_y, imgui.get_color_u32_rgba(1, 1, 1, 1), up_text)
    draw_list.add_text(down_pos_x, down_pos_y, imgui.get_color_u32_rgba(1, 1, 1, 1), down_text)

def draw_core_grid(draw_list, top_left, size, core_usages):
    """CPU 코어 사용률을 나타내는 색상 사각형 그리드를 그립니다."""
    num_cores = len(core_usages)
    if num_cores == 0:
        return

    cols = math.isqrt(num_cores)
    if cols == 0:
        cols = 1
    rows = (num_cores + cols - 1) // cols

    cell_size_x = size.x / cols
    cell_size_y = size.y / rows
    cell_side = min(cell_size_x, cell_size_y)

    grid_render_width = cell_side * cols
    grid_render_height = cell_side * rows
    offset_x = (size.x - grid_render_width) / 2
    offset_y = (size.y - grid_render_height) / 2
    
    padding = 2.0

    for i, usage in enumerate(core_usages):
        row = i // cols
        col = i % cols

        cell_x = top_left.x + offset_x + col * cell_side
        cell_y = top_left.y + offset_y + row * cell_side

        color = get_gradient_color(usage)
        
        draw_list.add_rect_filled(
            cell_x + padding,
            cell_y + padding,
            cell_x + cell_side - padding,
            cell_y + cell_side - padding,
            imgui.get_color_u32_rgba(*color),
            rounding=3.0
        )

def draw_disk_gauge(draw_list, center, radius, usage_percent, read_percent, write_percent, label, read_speed_mbps, write_speed_mbps, sub_text=None):
    """디스크 사용량, 읽기/쓰기 속도를 표시하는 게이지를 그립니다."""
    background_thickness = 8
    foreground_thickness = 12

    # R/W activity color
    color_percent = (read_percent + write_percent) / 2.0
    r, g, b, a = get_gradient_color(color_percent)
    main_color = imgui.get_color_u32_rgba(r, g, b, a)

    # Gauge background
    draw_list.add_circle(center.x, center.y, radius, imgui.get_color_u32_rgba(0.2, 0.2, 0.2, 1.0), num_segments=128, thickness=background_thickness)

    # Write speed arc (left)
    if write_percent > 0:
        angle_end_write = -math.pi / 2
        angle_start_write = angle_end_write - (min(write_percent, 100) / 100.0) * math.pi
        num_segments = int(64 * min(write_percent, 100) / 100)
        if num_segments < 2: num_segments = 2
        draw_list.path_clear()
        draw_list.path_arc_to(center.x, center.y, radius, angle_start_write, angle_end_write, num_segments=num_segments)
        draw_list.path_stroke(main_color, thickness=foreground_thickness)

    # Read speed arc (right)
    if read_percent > 0:
        angle_start_read = -math.pi / 2
        angle_end_read = angle_start_read + (min(read_percent, 100) / 100.0) * math.pi
        num_segments = int(64 * min(read_percent, 100) / 100)
        if num_segments < 2: num_segments = 2
        draw_list.path_clear()
        draw_list.path_arc_to(center.x, center.y, radius, angle_start_read, angle_end_read, num_segments=num_segments)
        draw_list.path_stroke(main_color, thickness=foreground_thickness)

    # Inner filled circle for usage
    if usage_percent > 0:
        inner_color = get_gradient_color(usage_percent)
        main_inner_color = imgui.get_color_u32_rgba(inner_color[0], inner_color[1], inner_color[2], 0.6)
        inner_radius = radius * (usage_percent / 100.0)
        draw_list.add_circle_filled(center.x, center.y, inner_radius, main_inner_color, num_segments=128)

    # R/W speed text in the center
    read_text = f"R: {read_speed_mbps:.1f}"
    write_text = f"W: {write_speed_mbps:.1f}"

    read_text_size = imgui.calc_text_size(read_text)
    write_text_size = imgui.calc_text_size(write_text)

    text_padding = 5
    total_height = read_text_size.y + write_text_size.y + text_padding
    
    read_pos_y = center.y - total_height / 2
    write_pos_y = read_pos_y + read_text_size.y + text_padding

    read_pos_x = center.x - read_text_size.x / 2
    write_pos_x = center.x - write_text_size.x / 2

    draw_list.add_text(read_pos_x, read_pos_y, imgui.get_color_u32_rgba(1, 1, 1, 1), read_text)
    draw_list.add_text(write_pos_x, write_pos_y, imgui.get_color_u32_rgba(1, 1, 1, 1), write_text)

    # Label below gauge
    label_size = imgui.calc_text_size(label)
    label_pos = imgui.Vec2(center.x - label_size.x / 2, center.y + radius + 15)
    draw_list.add_text(label_pos.x, label_pos.y, imgui.get_color_u32_rgba(0.8, 0.8, 0.8, 1), label)

    # Sub-text for total disk space
    if sub_text:
        sub_text_size = imgui.calc_text_size(sub_text)
        sub_text_pos = imgui.Vec2(center.x - sub_text_size.x / 2, label_pos.y + label_size.y + 5)
        draw_list.add_text(sub_text_pos.x, sub_text_pos.y, imgui.get_color_u32_rgba(0.7, 0.7, 0.7, 1), sub_text)

def main():
    if not glfw.init():
        print("GLFW를 초기화할 수 없습니다.", file=sys.stderr)
        return

    window = glfw.create_window(2400, 480, "Hardware Monitor (ImGui)", None, None)
    if not window:
        glfw.terminate()
        print("GLFW 창을 생성할 수 없습니다.", file=sys.stderr)
        return

    glfw.make_context_current(window)

    if sys.platform == 'win32':
        try:
            import ctypes
            hwnd = glfw.get_win32_window(window)
            DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR = 35, 36
            black, white = 0x00000000, 0x00FFFFFF
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(black)), ctypes.sizeof(ctypes.c_int))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_TEXT_COLOR, ctypes.byref(ctypes.c_int(white)), ctypes.sizeof(ctypes.c_int))
        except Exception as e:
            print(f"Windows 타이틀 바 색상 변경 실패: {e}", file=sys.stderr)

    imgui.create_context()
    impl = GlfwRenderer(window)
    
    io = imgui.get_io()
    io.fonts.clear()
    font_size = 32.0
    font_path = None

    if sys.platform == "win32":
        if 'WINDIR' in os.environ:
            fonts_dir = os.path.join(os.environ['WINDIR'], 'Fonts')
            font_files = ["seguisym.ttf", "Verdana.ttf", "Arial.ttf", "malgun.ttf"]
            for font_file in font_files:
                candidate_path = os.path.join(fonts_dir, font_file)
                if os.path.exists(candidate_path):
                    font_path = candidate_path
                    break
    
    if font_path:
        try:
            io.fonts.add_font_from_file_ttf(font_path, font_size)
            impl.refresh_font_texture()
            print(f"폰트 로드 성공: {font_path} ({font_size}px)")
        except (IOError, RuntimeError) as e:
            print(f"폰트 로드 오류: {e}. 기본 폰트를 사용합니다.", file=sys.stderr)
            font_path = None
    
    if not font_path:
        print("적절한 TTF 폰트를 찾지 못했습니다. ImGui 기본 폰트를 사용합니다.", file=sys.stderr)

    gpu_handle = init_nvml()

    target_fps = 10.0
    frame_duration = 1.0 / target_fps
    
    nic_speed = get_network_speed_mbps()
    max_upload_mbps = nic_speed
    max_download_mbps = nic_speed
    print(f"Network speed detected: {nic_speed} Mbps")

    last_net_io = psutil.net_io_counters()
    last_net_time = time.time()

    last_disk_io = psutil.disk_io_counters()
    last_disk_time = time.time()
    max_disk_rw_mbps = 1000  # 1GB/s

    while not glfw.window_should_close(window):
        frame_start_time = time.time()

        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        width, height = glfw.get_window_size(window)
        imgui.set_next_window_size(width, height)
        imgui.set_next_window_position(0, 0)
        
        imgui.begin("Background", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_MOVE | imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_BACKGROUND)

        # --- 데이터 수집 ---
        cpu_total_usage = psutil.cpu_percent(interval=None)
        cpu_core_usages = psutil.cpu_percent(interval=None, percpu=True)
        ram_percent, ram_used, ram_total = get_ram_usage()
        gpu_percent = get_gpu_usage(gpu_handle)
        vram_percent, vram_used, vram_total = get_gpu_memory_usage(gpu_handle)

        current_net_time = time.time()
        current_net_io = psutil.net_io_counters()
        time_delta = current_net_time - last_net_time

        if time_delta > 0:
            bytes_sent = current_net_io.bytes_sent - last_net_io.bytes_sent
            bytes_recv = current_net_io.bytes_recv - last_net_io.bytes_recv
            upload_speed_mbps = (bytes_sent * 8 / time_delta) / (1024**2)
            download_speed_mbps = (bytes_recv * 8 / time_delta) / (1024**2)
        else:
            upload_speed_mbps = 0
            download_speed_mbps = 0

        last_net_io = current_net_io
        last_net_time = current_net_time

        upload_percent = (upload_speed_mbps / max_upload_mbps) * 100 if max_upload_mbps > 0 else 0
        download_percent = (download_speed_mbps / max_download_mbps) * 100 if max_download_mbps > 0 else 0

        current_disk_time = time.time()
        current_disk_io = psutil.disk_io_counters()
        disk_time_delta = current_disk_time - last_disk_time

        if disk_time_delta > 0:
            bytes_read = current_disk_io.read_bytes - last_disk_io.read_bytes
            bytes_written = current_disk_io.write_bytes - last_disk_io.write_bytes
            read_speed_mbps = (bytes_read / disk_time_delta) / (1024**2)
            write_speed_mbps = (bytes_written / disk_time_delta) / (1024**2)
        else:
            read_speed_mbps = 0
            write_speed_mbps = 0
        
        last_disk_io = current_disk_io
        last_disk_time = current_disk_time

        read_percent = (read_speed_mbps / max_disk_rw_mbps) * 100
        write_percent = (write_speed_mbps / max_disk_rw_mbps) * 100

        disk_info_c = get_disk_info('C')

        # --- 그리기 ---
        draw_list = imgui.get_window_draw_list()
        
        gauge_radius = min(width, height) * 0.25
        center_y = height / 2
        
        # Item widths
        cpu_grid_width = (gauge_radius * 2 * 0.5) + 20
        cpu_total_width = (gauge_radius * 2) + cpu_grid_width
        regular_gauge_width = gauge_radius * 2
        
        # Spacing calculation for 4 items
        total_content_width = cpu_total_width + (regular_gauge_width * 3)
        spacing = (width - total_content_width) / 5 # 4 items, 5 gaps

        # Positions
        pos1_x = spacing + cpu_total_width / 2
        pos2_x = pos1_x + cpu_total_width / 2 + spacing + regular_gauge_width / 2
        pos3_x = pos2_x + regular_gauge_width / 2 + spacing + regular_gauge_width / 2
        pos4_x = pos3_x + regular_gauge_width / 2 + spacing + regular_gauge_width / 2

        # 1. CPU / RAM
        cpu_ram_center_x = pos1_x - cpu_grid_width / 2
        cpu_ram_center = imgui.Vec2(cpu_ram_center_x, center_y)
        draw_combined_gauge(draw_list, cpu_ram_center, gauge_radius, cpu_total_usage, ram_percent, "CPU / RAM", f"{ram_used:.1f}/{ram_total:.1f} GB")
        grid_area_size = gauge_radius * 2 * 0.5
        grid_size = imgui.Vec2(grid_area_size, grid_area_size)
        grid_top_left = imgui.Vec2(cpu_ram_center.x + gauge_radius + 20, center_y - grid_size.y / 2)
        draw_core_grid(draw_list, grid_top_left, grid_size, cpu_core_usages)

        # 2. GPU / VRAM
        draw_combined_gauge(draw_list, imgui.Vec2(pos2_x, center_y), gauge_radius, gpu_percent, vram_percent, "GPU / VRAM", f"{vram_used:.0f}/{vram_total:.0f} MB")

        # 3. Network
        draw_network_gauge(draw_list, imgui.Vec2(pos3_x, center_y), gauge_radius, upload_percent, download_percent, "Network", upload_speed_mbps, download_speed_mbps)

        # 4. Disk C:
        if disk_info_c:
            draw_disk_gauge(
                draw_list,
                imgui.Vec2(pos4_x, center_y),
                gauge_radius,
                disk_info_c['percent'],
                read_percent,
                write_percent,
                "Disk (C:)",
                read_speed_mbps,
                write_speed_mbps,
                f"{disk_info_c['used_gb']:.1f}/{disk_info_c['total_gb']:.1f} GB"
            )

        imgui.end()

        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        
        imgui.render()
        impl.render(imgui.get_draw_data())
        
        glfw.swap_buffers(window)

        # Frame rate limiting
        elapsed_time = time.time() - frame_start_time
        sleep_time = frame_duration - elapsed_time
        if sleep_time > 0:
            time.sleep(sleep_time)

    if nvml_initialized:
        pynvml.nvmlShutdown()
    impl.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
