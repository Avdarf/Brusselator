import cv2
import os
import json
import numpy as np
import matplotlib.pyplot as plt
from pde import PDE, FieldCollection, ScalarField, CartesianGrid, MemoryStorage
import logging
import colorlog
from multiprocessing import Pool

def setup_logging(render_dir):
    """Set up logging to file and console with color."""
    log_file = os.path.join(render_dir, 'processing.log')

    # Create a logger object
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Create handlers
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)

    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(logging.ERROR)

    # Create formatters
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_formatter = colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
        log_colors={
            'ERROR': 'red',
            'WARNING': 'yellow',
            'INFO': 'green',
            'DEBUG': 'blue'
        }
    )

    # Add formatters to handlers
    file_handler.setFormatter(file_formatter)
    console_handler.setFormatter(console_formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

def write_settings_to_file(settings, render_dir):
    """Write settings to a text file."""
    settings_path = os.path.join(render_dir, 'settings.txt')
    with open(settings_path, 'w') as f:
        f.write("Settings:\n")
        json.dump(settings, f, indent=4)

def check_for_invalid_values(state_data, title, time_point):
    """Check for invalid values in the state data."""
    if np.isnan(state_data).any() or np.isinf(state_data).any():
        logging.error(f"Invalid values encountered in mode {title} at time {time_point}.")
        return True
    return False

def print_debug_info(state_data, title, time_point):
    """Print debug information for state data."""
    logging.debug(f"Debug info for mode {title} at time {time_point}:")
    logging.debug(f"Min value: {np.min(state_data)}, Max value: {np.max(state_data)}")
    logging.debug(f"Mean value: {np.mean(state_data)}, Std dev: {np.std(state_data)}")

def process_mode(mode, render_dir, settings):
    title = mode["title"]
    a = mode["a"]
    b = mode["b"]
    d0 = mode["d0"]
    d1 = mode["d1"]
    filename = mode["filename"]
    description = mode["description"]

    logging.info(f"Starting mode {title}")

    # Define the PDE
    eq = PDE(
        {
            "u": f"{d0} * laplace(u) + {a} - ({b} + 1) * u + u**2 * v",
            "v": f"{d1} * laplace(v) + {b} * u - u**2 * v",
        }
    )

    # Initialize state with reflective boundary conditions
    RADIUS = 1 / settings["ZOOM_FACTOR"]
    grid = CartesianGrid([[-RADIUS, RADIUS], [-RADIUS, RADIUS]], [settings["RESOLUTION"], settings["RESOLUTION"]], periodic=not settings["FIXED_BOUNDARY"])

    u = ScalarField(grid, a, label="Field $u$")
    v = b / a + 0.1 * ScalarField.random_normal(grid, label="Field $v$")

    center = (grid.shape[0] // 2, grid.shape[1] // 2)
    Y, X = np.ogrid[:grid.shape[0], :grid.shape[1]]
    dist_from_center = np.sqrt((X - center[1]) ** 2 + (Y - center[0]) ** 2)
    circular_mask = dist_from_center <= (RADIUS * (settings["RESOLUTION"] / (2 * RADIUS)))

    if settings["FIXED_BOUNDARY"]:
        u.data[~circular_mask] = 0
        v.data[~circular_mask] = 0

    state = FieldCollection([u, v])

    frames_dir = os.path.join(render_dir, f'frames_{title.replace(" ", "_").lower()}')
    os.makedirs(frames_dir, exist_ok=True)
    logging.debug(f"Frames directory created for mode {title} at {frames_dir}")

    storage = MemoryStorage()

    try:
        sol = eq.solve(state, t_range=settings["T_MAX"], dt=settings["DT"], tracker=storage.tracker(interval=1))
        for time_point, state_data in storage.items():
            if check_for_invalid_values(state_data.data, title, time_point):
                print_debug_info(state_data.data, title, time_point)
                raise ValueError(f"Invalid values encountered in mode {title} at time {time_point}.")
    except (RuntimeWarning, ValueError) as e:
        logging.error(f"Warning or error encountered in mode {title}: {e}")
        return

    storage_dict = list(storage.items())
    width, height = None, None

    for frame_idx, (time, state) in enumerate(storage_dict):
        fig, ax = plt.subplots(figsize=(8, 8))

        u_data = np.ma.masked_where(~circular_mask, state[0].data)
        v_data = np.ma.masked_where(~circular_mask, state[1].data)

        u_plot = ax.imshow(u_data, cmap=settings["U_COLOR"], alpha=0.6, vmin=settings["COLOR_VMIN"], vmax=settings["COLOR_VMAX"], extent=[-RADIUS, RADIUS, -RADIUS, RADIUS])

        v_plot = ax.imshow(v_data, cmap=settings["V_COLOR"], alpha=0.6, vmin=settings["COLOR_VMIN"], vmax=settings["COLOR_VMAX"], extent=[-RADIUS, RADIUS, -RADIUS, RADIUS])

        cbar_u = plt.colorbar(u_plot, ax=ax, fraction=0.046, pad=0.12)
        cbar_u.ax.set_ylabel('Compound X', labelpad=10)

        cbar_v = plt.colorbar(v_plot, ax=ax, fraction=0.046, pad=0.22)
        cbar_v.ax.set_ylabel('Compound Y', labelpad=10)

        plt.title(title, fontweight='bold')
        ax.set_xlabel('x')
        ax.set_ylabel('y')

        params_text = f'a = {a}\nb = {b}\nd0 = {d0}\nd1 = {d1}'
        ax.text(-RADIUS + 0.05, -RADIUS + 0.05, params_text, ha='left', va='bottom',
                bbox=dict(facecolor='white', alpha=0.5, edgecolor='black'))

        plt.figtext(0.5, 0.06, description, ha="center", fontsize=10, wrap=True, bbox=dict(facecolor='white', alpha=0.5, edgecolor='black'))

        frame_path = os.path.join(frames_dir, f'frame_{frame_idx:04d}.png')
        plt.savefig(frame_path, bbox_inches='tight', dpi=150)
        plt.close(fig)
        logging.info(f"Saved frame {frame_idx} for mode {title} at time {time}")

        if width is None or height is None:
            first_frame = cv2.imread(frame_path)
            if first_frame is not None:
                height, width, layers = first_frame.shape

    logging.info(f"Finished processing mode {title}")

    video_path = os.path.join(render_dir, filename)

    first_frame = cv2.imread(os.path.join(frames_dir, 'frame_0000.png'))
    if first_frame is None:
        raise ValueError("First frame not found. Check if the frames are being saved correctly.")
    height, width, layers = first_frame.shape
    frame_size = (width, height)

    out = cv2.VideoWriter(video_path, cv2.VideoWriter_fourcc(*'mp4v'), settings["FRAME_RATE"], frame_size)

    frame_files = sorted([f for f in os.listdir(frames_dir) if f.endswith('.png')])
    for frame_file in frame_files:
        frame = cv2.imread(os.path.join(frames_dir, frame_file))
        if frame is None:
            logging.warning(f"Error reading frame {frame_file}. Skipping.")
            continue
        out.write(frame)

    out.release()
    logging.info(f"Video saved to {video_path}")

def main():
    # Load settings from external JSON file
    with open('settings.json', 'r') as f:
        settings = json.load(f)

    # Extract constants from settings
    RESOLUTION = settings["resolution"]
    FRAME_RATE = settings["frame_rate"]
    T_MAX = settings["t_max"]
    DT = settings["dt"] / 100  # Further reduce the time step to improve stability
    COLOR_VMIN = settings["color_vmin"]
    COLOR_VMAX = settings["color_vmax"]
    U_COLOR = settings["u_color"]
    V_COLOR = settings["v_color"]
    FIXED_BOUNDARY = settings["fixed_boundary"]
    ZOOM_FACTOR = settings["zoom_factor"]

    # Update settings dictionary with extracted constants
    settings.update({
        "RESOLUTION": RESOLUTION,
        "FRAME_RATE": FRAME_RATE,
        "T_MAX": T_MAX,
        "DT": DT,
        "COLOR_VMIN": COLOR_VMIN,
        "COLOR_VMAX": COLOR_VMAX,
        "U_COLOR": U_COLOR,
        "V_COLOR": V_COLOR,
        "FIXED_BOUNDARY": FIXED_BOUNDARY,
        "ZOOM_FACTOR": ZOOM_FACTOR
    })

    # Create results directory
    results_dir = 'results'
    os.makedirs(results_dir, exist_ok=True)

    # Determine the next render number
    render_numbers = [int(name) for name in os.listdir(results_dir) if name.isdigit()]
    render_number = max(render_numbers, default=0) + 1
    render_dir = os.path.join(results_dir, str(render_number))
    os.makedirs(render_dir, exist_ok=True)
    logging.info(f"Created results directory: {render_dir}")

    # Set up logging
    setup_logging(render_dir)
    logging.info("Logging configured")

    # Save settings to file before starting any processing
    write_settings_to_file(settings, render_dir)
    logging.info(f"Settings saved to {os.path.join(render_dir, 'settings.txt')}")

    # Process modes in parallel
    pool = Pool()
    results = [pool.apply_async(process_mode, (mode, render_dir, settings)) for mode in settings["modes"]]
    pool.close()
    pool.join()

    logging.info(f"All modes processed.")

if __name__ == "__main__":
    main()

