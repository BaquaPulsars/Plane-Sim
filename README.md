# Plane Boarding Simulation

A visual, interactive simulation of different airline boarding strategies built with Python and Pygame.

## Requirements

- Python 3.8 or higher
- Pygame

Install Pygame with:

```
pip install pygame
```

## Features

### Boarding Methods

| Method | Description |
|---|---|
| **Front to Back** | Passengers near the boarding gate board first, filling toward the back of the plane |
| **Back to Front** | Passengers at the back of the plane board first, filling toward the front |
| **WILMA** | Window seats board first, then Middle, then Aisle — minimises seat-blocking delays |
| **Steffen** | Alternates even/odd rows by seat type for minimal aisle congestion |
| **Random** | No grouping — passengers board in a random order |

### Passenger Behaviour

- Passengers walk down the aisle row by row and stop one row behind anyone ahead of them
- On reaching their row they spend time stowing luggage (shown as a yellow progress arc)
- If a seated passenger is blocking access to a window or middle seat, the boarding passenger waits for them to stand aside (shown in red) before sitting down
- All wait times include a random component so no two runs are identical

### Adjustable Parameters

| Slider | Range | Effect |
|---|---|---|
| **Capacity** | 10% – 100% | Percentage of seats that are occupied |
| **Compliance** | 0% – 100% | How strictly passengers follow their boarding group order. At 0% it is effectively random |
| **Speed** | 0.25× – 8× | Simulation playback speed |

### Statistics Panel

Displays the current boarding method, number of seated passengers, elapsed time, and a progress bar. When all passengers are seated the total boarding time is shown.

### Colour Legend

| Colour | Meaning |
|---|---|
| Purple | Walking down the aisle |
| Yellow | Stowing luggage |
| Red | Waiting for a blocked seat to clear |
| Green | Seated |

## Usage

Run the simulation from the command line:

```
python plane.py
```

### Controls

| Input | Action |
|---|---|
| **Space** | Pause / resume |
| **R** | Restart with the current settings |
| **Method buttons** | Switch boarding strategy (restarts automatically on next run) |
| **Sliders** | Adjust capacity, compliance, and speed in real time |
| **Restart button** | Start a new run with all current settings applied |

## Example

To compare Back to Front against WILMA at 80% capacity:

1. Run `python plane.py`
2. Set **Capacity** to 80% using the slider
3. Leave **Compliance** at 90% (default)
4. Select **Back to Front** and click **Restart** — note the total boarding time when the green "DONE" message appears
5. Select **WILMA** and click **Restart** — compare the boarding time

Increasing the **Speed** slider to 4× or 8× lets you run through comparisons quickly. Lowering **Compliance** to 0% simulates a real-world gate where passengers ignore group assignments entirely.
