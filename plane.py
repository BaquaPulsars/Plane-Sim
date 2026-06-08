import pygame
import random
import math
import sys
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1200, 800
FPS = 60

# Layout
AISLE_X_LEFT   = 480   # left edge of aisle column (pixels)
AISLE_X_RIGHT  = 520
AISLE_X_CENTER = 500
ROW_HEIGHT     = 28
FIRST_ROW_Y    = 80
NUM_ROWS       = 20
SEATS_PER_SIDE = 3     # A-B-C  |aisle|  D-E-F

SEAT_W, SEAT_H = 36, 22
SEAT_GAP       = 4

PASSENGER_R    = 9

# Timing (seconds)
LUGGAGE_TIME_BASE  = 3.0
LUGGAGE_TIME_RAND  = 2.0
BLOCKED_WAIT_BASE  = 2.0
BLOCKED_WAIT_RAND  = 1.0
AISLE_STEP_TIME    = 0.25   # seconds per row of aisle movement

# Colors
C_BG          = (30,  30,  40)
C_PLANE_BODY  = (55,  60,  80)
C_SEAT_EMPTY  = (80,  90, 110)
C_SEAT_TAKEN  = (60, 140,  80)
C_SEAT_TARGET = (200, 180,  40)
C_AISLE       = (45,  50,  65)
C_PASSENGER   = (220, 200, 160)
C_PASSENGER_MOVING = (160, 80, 220)
C_PASSENGER_SEATED = (80, 200, 120)
C_PASSENGER_WAIT   = (240, 140,  60)
C_TEXT        = (220, 220, 230)
C_HEADER      = (180, 200, 255)
C_BTN         = (70,  80, 110)
C_BTN_HOVER   = (100, 115, 160)
C_BTN_ACTIVE  = (60, 130, 200)

GROUP_COLORS = [
    (220,  80,  80),
    (220, 160,  60),
    ( 80, 200, 120),
    ( 80, 160, 220),
    (180,  80, 220),
    (220, 220,  60),
]

# ── Seat geometry ─────────────────────────────────────────────────────────────

def seat_pixel(row: int, col: int) -> Tuple[int, int]:
    """Return top-left pixel of a seat. col 0-2 = left side (A-B-C), col 3-5 = right (D-E-F)."""
    y = FIRST_ROW_Y + row * ROW_HEIGHT
    if col < SEATS_PER_SIDE:
        x = AISLE_X_LEFT - (SEATS_PER_SIDE - col) * (SEAT_W + SEAT_GAP)
    else:
        x = AISLE_X_RIGHT + (col - SEATS_PER_SIDE) * (SEAT_W + SEAT_GAP)
    return (x, y)

def seat_center(row: int, col: int) -> Tuple[int, int]:
    sx, sy = seat_pixel(row, col)
    return (sx + SEAT_W // 2, sy + SEAT_H // 2)

def aisle_y(row: int) -> int:
    return FIRST_ROW_Y + row * ROW_HEIGHT + SEAT_H // 2

# ── Enums / State ─────────────────────────────────────────────────────────────

class PState(Enum):
    QUEUE     = "queue"
    ENTERING  = "entering"   # walking down aisle toward target row
    STORING   = "storing"    # arrived at row, storing luggage
    BLOCKED   = "blocked"    # someone in the way, waiting
    SEATED    = "seated"

# ── Passenger ─────────────────────────────────────────────────────────────────

@dataclass
class Passenger:
    pid: int
    row: int
    col: int
    group: int
    color: tuple

    state: PState = PState.QUEUE
    aisle_row: float = float(NUM_ROWS)  # current aisle row position (float for smooth movement)
    timer: float = 0.0                  # countdown for luggage/blocked wait
    luggage_time: float = 0.0
    seated_time: float = 0.0           # time when seated (for stats)
    px: float = 0.0                    # pixel x
    py: float = 0.0                    # pixel y

    def target_aisle_row(self) -> float:
        return float(self.row)

    def is_blocking_others(self) -> bool:
        return self.state in (PState.STORING, PState.BLOCKED)

# ── Simulation ────────────────────────────────────────────────────────────────

class PlaneSimulation:
    def __init__(self, method: str, capacity: float, compliance: float):
        self.method     = method
        self.capacity   = capacity    # 0.0-1.0
        self.compliance = compliance  # 0.0-1.0 (how well groups are respected)
        self.reset()

    def reset(self):
        self.passengers: List[Passenger] = []
        self.queue: List[Passenger] = []
        self.aisle: List[Optional[Passenger]] = [None] * NUM_ROWS  # who occupies each aisle row
        self.seated_count = 0
        self.elapsed = 0.0
        self.done = False
        self.total_time = 0.0
        self._build_passengers()
        self._assign_queue()

    def _build_passengers(self):
        seats = [(r, c) for r in range(NUM_ROWS) for c in range(SEATS_PER_SIDE * 2)]
        random.shuffle(seats)
        n = max(1, int(len(seats) * self.capacity))
        seats = seats[:n]

        for i, (r, c) in enumerate(seats):
            color = (160, 80, 220)
            p = Passenger(pid=i, row=r, col=c, group=0, color=color)
            p.luggage_time = LUGGAGE_TIME_BASE + random.random() * LUGGAGE_TIME_RAND
            self.passengers.append(p)

    def _assign_queue(self):
        """Assign boarding groups and order the queue based on method."""
        method = self.method

        def assign_groups():
            if method == "Back to Front":
                for p in self.passengers:
                    # row 0 (back/top) = group 0, boards first
                    p.group = p.row // 5
            elif method == "Front to Back":
                for p in self.passengers:
                    # row 19 (front/bottom) = group 0, boards first
                    p.group = (NUM_ROWS - 1 - p.row) // 5
            elif method == "WILMA":
                col_order = {0: 0, 5: 0, 1: 1, 4: 1, 2: 2, 3: 2}  # W, M, A
                for p in self.passengers:
                    p.group = col_order[p.col]
            elif method == "Steffen":
                # Even rows window first, then odd rows window, then even middle, etc.
                # Steffen perfect: specific interleaving by row-parity and seat type
                col_order = {0: 0, 5: 0, 1: 2, 4: 2, 2: 4, 3: 4}
                for p in self.passengers:
                    parity = 0 if p.row % 2 == 0 else 1
                    p.group = col_order[p.col] + parity
            elif method == "Random":
                for p in self.passengers:
                    p.group = 0

        assign_groups()

        # Sort by group, with compliance noise
        def sort_key(p):
            noise = random.gauss(0, (1.0 - self.compliance) * 3)
            return p.group + noise

        self.queue = sorted(self.passengers, key=sort_key)
        # Position them in queue (off screen, below plane)
        for i, p in enumerate(self.queue):
            p.px = float(AISLE_X_CENTER)
            p.py = float(SCREEN_H - 30 - i * 4)
            p.aisle_row = float(NUM_ROWS + 2)
            p.state = PState.QUEUE

    def update(self, dt: float):
        if self.done:
            return
        self.elapsed += dt

        # Let next passenger enter if aisle entrance (row NUM_ROWS-1) is free
        # and previous passenger has moved at least 1 row in
        if self.queue:
            entrance_clear = True
            for p in self.passengers:
                if p.state in (PState.ENTERING, PState.STORING, PState.BLOCKED):
                    if p.aisle_row >= NUM_ROWS - 1:
                        entrance_clear = False
                        break
            if entrance_clear:
                next_p = self.queue.pop(0)
                next_p.state = PState.ENTERING
                next_p.aisle_row = float(NUM_ROWS - 0.5)

        # Update each active passenger
        for p in self.passengers:
            if p.state == PState.QUEUE or p.state == PState.SEATED:
                continue

            if p.state == PState.ENTERING:
                self._update_entering(p, dt)
            elif p.state == PState.STORING:
                self._update_storing(p, dt)
            elif p.state == PState.BLOCKED:
                self._update_blocked(p, dt)

            # Update pixel position
            if p.state != PState.SEATED:
                target_py = float(aisle_y(min(int(p.aisle_row), NUM_ROWS - 1)))
                if p.aisle_row >= NUM_ROWS:
                    target_py = float(SCREEN_H - 60)
                p.py = target_py
                p.px = float(AISLE_X_CENTER)

        # Check done
        if not self.queue and all(p.state == PState.SEATED for p in self.passengers):
            self.done = True
            self.total_time = self.elapsed

    def _aisle_blocked_at(self, row: int, excluding: Passenger) -> bool:
        """Is there a passenger stopped at this aisle row (not the given one)?"""
        target_row = int(row)
        for p in self.passengers:
            if p is excluding:
                continue
            if p.state in (PState.STORING, PState.BLOCKED):
                if int(p.aisle_row) == target_row:
                    return True
        return False

    def _passenger_ahead(self, p: Passenger) -> bool:
        """Is there a passenger directly ahead (lower row number = closer to front)?"""
        target_row = p.aisle_row - 1.0
        if target_row < 0:
            return False
        for other in self.passengers:
            if other is p:
                continue
            if other.state in (PState.ENTERING, PState.STORING, PState.BLOCKED):
                if abs(other.aisle_row - target_row) < 0.8:
                    return True
        return False

    def _update_entering(self, p: Passenger, dt: float):
        target = float(p.row)

        # Find the nearest active passenger ahead (lower aisle_row = closer to front).
        nearest_ahead_row = None
        for other in self.passengers:
            if other is p or other.state in (PState.QUEUE, PState.SEATED):
                continue
            if other.aisle_row < p.aisle_row:
                if nearest_ahead_row is None or other.aisle_row > nearest_ahead_row:
                    nearest_ahead_row = other.aisle_row

        # Stay at least 1 row behind the nearest blocker, but never past target.
        if nearest_ahead_row is not None:
            effective_target = max(target, nearest_ahead_row + 1.0)
        else:
            effective_target = target

        # Advance toward effective_target.
        if p.aisle_row > effective_target + 0.05:
            move = dt / AISLE_STEP_TIME
            p.aisle_row = max(effective_target, p.aisle_row - move)

        # Trigger arrival only when we've reached our actual seat row.
        if p.aisle_row <= target + 0.05:
            p.aisle_row = target
            if self._seat_blocked(p):
                p.state = PState.BLOCKED
                p.timer = BLOCKED_WAIT_BASE + random.random() * BLOCKED_WAIT_RAND
            else:
                p.state = PState.STORING
                p.timer = p.luggage_time

    def _seat_blocked(self, p: Passenger) -> bool:
        """Check if someone is seated between p and the aisle (window/middle needing aisle to be empty)."""
        aisle_col = 2 if p.col < SEATS_PER_SIDE else 3
        inner_cols = list(range(p.col + 1, aisle_col + 1)) if p.col < SEATS_PER_SIDE else list(range(aisle_col, p.col))
        for other in self.passengers:
            if other.row == p.row and other.col in inner_cols and other.state == PState.SEATED:
                return True
        return False

    def _update_storing(self, p: Passenger, dt: float):
        p.timer -= dt
        if p.timer <= 0:
            p.state = PState.SEATED
            cx, cy = seat_center(p.row, p.col)
            p.px, p.py = float(cx), float(cy)
            self.seated_count += 1

    def _update_blocked(self, p: Passenger, dt: float):
        p.timer -= dt
        if p.timer <= 0:
            # Timer represents the obstructing passenger standing aside — always proceed after.
            p.state = PState.STORING
            p.timer = p.luggage_time


# ── UI Helpers ────────────────────────────────────────────────────────────────

class Button:
    def __init__(self, x, y, w, h, label, value=None):
        self.rect  = pygame.Rect(x, y, w, h)
        self.label = label
        self.value = value if value is not None else label
        self.active = False

    def draw(self, surf, font, hover=False):
        color = C_BTN_ACTIVE if self.active else (C_BTN_HOVER if hover else C_BTN)
        pygame.draw.rect(surf, color, self.rect, border_radius=6)
        pygame.draw.rect(surf, C_HEADER, self.rect, 1, border_radius=6)
        txt = font.render(self.label, True, C_TEXT)
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def hit(self, pos):
        return self.rect.collidepoint(pos)


class Slider:
    def __init__(self, x, y, w, label, lo, hi, value, fmt="{:.0%}"):
        self.x, self.y, self.w = x, y, w
        self.label = label
        self.lo, self.hi = lo, hi
        self.value = value
        self.fmt   = fmt
        self.dragging = False
        self.track = pygame.Rect(x, y + 18, w, 6)
        self._update_knob()

    def _update_knob(self):
        t = (self.value - self.lo) / (self.hi - self.lo)
        kx = self.x + int(t * self.w)
        self.knob = pygame.Rect(kx - 7, self.y + 12, 14, 18)

    def draw(self, surf, font, hover=False):
        # Label + value
        lbl = font.render(f"{self.label}: {self.fmt.format(self.value)}", True, C_HEADER)
        surf.blit(lbl, (self.x, self.y))
        # Track
        pygame.draw.rect(surf, (60, 70, 90), self.track, border_radius=3)
        t = (self.value - self.lo) / (self.hi - self.lo)
        filled = pygame.Rect(self.x, self.y + 18, int(t * self.w), 6)
        pygame.draw.rect(surf, C_BTN_ACTIVE, filled, border_radius=3)
        # Knob
        color = C_BTN_HOVER if (hover or self.dragging) else C_BTN
        pygame.draw.rect(surf, color, self.knob, border_radius=4)
        pygame.draw.rect(surf, C_HEADER, self.knob, 1, border_radius=4)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.knob.collidepoint(event.pos):
            self.dragging = True
        elif event.type == pygame.MOUSEBUTTONUP:
            self.dragging = False
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            t = max(0.0, min(1.0, (event.pos[0] - self.x) / self.w))
            self.value = self.lo + t * (self.hi - self.lo)
            self._update_knob()

    def hit(self, pos):
        return self.track.collidepoint(pos) or self.knob.collidepoint(pos)


# ── Main App ──────────────────────────────────────────────────────────────────

class App:
    METHODS = ["Back to Front", "Front to Back", "WILMA", "Steffen", "Random"]

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Plane Boarding Simulation")
        self.clock  = pygame.time.Clock()
        self.font   = pygame.font.SysFont("segoeui", 15)
        self.font_s = pygame.font.SysFont("segoeui", 13)
        self.font_b = pygame.font.SysFont("segoeui", 18, bold=True)
        self.font_t = pygame.font.SysFont("segoeui", 22, bold=True)

        self.speed  = 1.0   # simulation speed multiplier
        self.paused = False
        self.method = "Back to Front"

        # Control panel area: right side x > 750
        px = 780
        self._build_controls(px)

        self.sim: Optional[PlaneSimulation] = None
        self._start_sim()

    def _build_controls(self, px):
        self.method_buttons = []
        for i, m in enumerate(self.METHODS):
            btn = Button(px, 80 + i * 38, 180, 30, m)
            if m == self.method:
                btn.active = True
            self.method_buttons.append(btn)

        self.cap_slider    = Slider(px, 300, 180, "Capacity",   0.1, 1.0, 0.85)
        self.comp_slider   = Slider(px, 350, 180, "Compliance", 0.0, 1.0, 0.90)
        self.speed_slider  = Slider(px, 400, 180, "Speed",      0.25, 8.0, 1.0, fmt="{:.2f}x")

        self.btn_start  = Button(px,       460, 86,  34, "Restart")
        self.btn_pause  = Button(px + 94,  460, 86,  34, "Pause")

    def _start_sim(self):
        self.sim = PlaneSimulation(self.method, self.cap_slider.value, self.comp_slider.value)

    def run(self):
        while True:
            dt_ms = self.clock.tick(FPS)
            dt    = (dt_ms / 1000.0) * self.speed_slider.value
            if self.paused:
                dt = 0.0

            mouse = pygame.mouse.get_pos()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit(); sys.exit()
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    if event.key == pygame.K_r:
                        self._start_sim()

                self.cap_slider.handle_event(event)
                self.comp_slider.handle_event(event)
                self.speed_slider.handle_event(event)

                if event.type == pygame.MOUSEBUTTONDOWN:
                    for btn in self.method_buttons:
                        if btn.hit(event.pos):
                            self.method = btn.value
                            for b in self.method_buttons:
                                b.active = (b.value == self.method)
                    if self.btn_start.hit(event.pos):
                        self._start_sim()
                    if self.btn_pause.hit(event.pos):
                        self.paused = not self.paused
                        self.btn_pause.label = "Resume" if self.paused else "Pause"

            if self.sim:
                self.sim.update(dt)

            self._draw(mouse)
            pygame.display.flip()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, mouse):
        self.screen.fill(C_BG)
        self._draw_plane()
        self._draw_passengers()
        self._draw_panel(mouse)
        self._draw_stats()

    def _draw_plane(self):
        # Fuselage background
        plane_rect = pygame.Rect(AISLE_X_LEFT - SEATS_PER_SIDE * (SEAT_W + SEAT_GAP) - 10,
                                 FIRST_ROW_Y - 15,
                                 AISLE_X_RIGHT - AISLE_X_LEFT + SEATS_PER_SIDE * (SEAT_W + SEAT_GAP) * 2 + 20,
                                 NUM_ROWS * ROW_HEIGHT + 30)
        pygame.draw.rect(self.screen, C_PLANE_BODY, plane_rect, border_radius=12)

        # Aisle
        aisle_rect = pygame.Rect(AISLE_X_LEFT, FIRST_ROW_Y - 10, AISLE_X_RIGHT - AISLE_X_LEFT, NUM_ROWS * ROW_HEIGHT + 20)
        pygame.draw.rect(self.screen, C_AISLE, aisle_rect)

        # Seats
        for row in range(NUM_ROWS):
            # Row label
            rl = self.font_s.render(str(row + 1), True, (120, 130, 150))
            self.screen.blit(rl, (AISLE_X_CENTER - 8, FIRST_ROW_Y + row * ROW_HEIGHT + 4))
            for col in range(SEATS_PER_SIDE * 2):
                sx, sy = seat_pixel(row, col)
                # Check occupation
                color = C_SEAT_EMPTY
                for p in (self.sim.passengers if self.sim else []):
                    if p.row == row and p.col == col and p.state == PState.SEATED:
                        color = C_SEAT_TAKEN
                        break
                pygame.draw.rect(self.screen, color, (sx, sy, SEAT_W, SEAT_H), border_radius=4)

        # Nose arrow (boarding direction indicator)
        tip_x = AISLE_X_CENTER
        top_y = FIRST_ROW_Y - 30
        pygame.draw.polygon(self.screen, (100, 120, 160),
                            [(tip_x, top_y), (tip_x - 12, top_y + 20), (tip_x + 12, top_y + 20)])
        lbl = self.font_s.render("BACK", True, (140, 160, 200))
        self.screen.blit(lbl, (tip_x - 20, top_y - 16))

        # Board entrance arrow
        ent_y = FIRST_ROW_Y + NUM_ROWS * ROW_HEIGHT + 18
        pygame.draw.polygon(self.screen, (80, 160, 220),
                            [(tip_x, ent_y - 10), (tip_x - 10, ent_y + 8), (tip_x + 10, ent_y + 8)])
        lbl2 = self.font_s.render("BOARD", True, (80, 160, 220))
        self.screen.blit(lbl2, (tip_x - 18, ent_y + 10))

    def _draw_passengers(self):
        if not self.sim:
            return
        queue_x = AISLE_X_CENTER
        queue_start_y = SCREEN_H - 40

        # Queue visualization (stacked below)
        for i, p in enumerate(self.sim.queue):
            qy = queue_start_y - i * 5
            if qy < FIRST_ROW_Y + NUM_ROWS * ROW_HEIGHT + 40:
                break
            pygame.draw.circle(self.screen, p.color, (queue_x, qy), 4)

        for p in self.sim.passengers:
            if p.state == PState.QUEUE:
                continue

            if p.state == PState.SEATED:
                color = C_PASSENGER_SEATED
                pygame.draw.circle(self.screen, color, (int(p.px), int(p.py)), PASSENGER_R - 2)
            elif p.state == PState.STORING:
                color = C_PASSENGER_WAIT
                pygame.draw.circle(self.screen, color, (int(p.px), int(p.py)), PASSENGER_R)
                # Progress arc
                if p.luggage_time > 0:
                    frac = 1.0 - p.timer / p.luggage_time
                    arc_rect = pygame.Rect(int(p.px) - PASSENGER_R, int(p.py) - PASSENGER_R,
                                           PASSENGER_R * 2, PASSENGER_R * 2)
                    try:
                        pygame.draw.arc(self.screen, (255, 255, 100), arc_rect,
                                        math.pi / 2, math.pi / 2 + frac * 2 * math.pi, 3)
                    except Exception:
                        pass
            elif p.state == PState.BLOCKED:
                color = (220, 80, 80)
                pygame.draw.circle(self.screen, color, (int(p.px), int(p.py)), PASSENGER_R)
            else:  # ENTERING
                color = p.color
                pygame.draw.circle(self.screen, color, (int(p.px), int(p.py)), PASSENGER_R)

            # Group dot
            pygame.draw.circle(self.screen, GROUP_COLORS[p.group % len(GROUP_COLORS)],
                                (int(p.px) + PASSENGER_R - 2, int(p.py) - PASSENGER_R + 2), 3)

    def _draw_panel(self, mouse):
        px = 770
        # Panel background
        panel = pygame.Rect(px, 40, SCREEN_W - px - 10, SCREEN_H - 60)
        pygame.draw.rect(self.screen, (40, 45, 60), panel, border_radius=10)
        pygame.draw.rect(self.screen, (70, 80, 110), panel, 1, border_radius=10)

        title = self.font_b.render("Boarding Method", True, C_HEADER)
        self.screen.blit(title, (px + 10, 52))

        for btn in self.method_buttons:
            btn.draw(self.screen, self.font, btn.hit(mouse))

        self.cap_slider.draw(self.screen, self.font_s)
        self.comp_slider.draw(self.screen, self.font_s)
        self.speed_slider.draw(self.screen, self.font_s)

        self.btn_start.draw(self.screen, self.font, self.btn_start.hit(mouse))
        self.btn_pause.draw(self.screen, self.font, self.btn_pause.hit(mouse))

        # Legend
        ly = 510
        self.screen.blit(self.font_s.render("Legend:", True, C_HEADER), (px + 10, ly))
        legend = [
            (C_PASSENGER_MOVING, "Walking"),
            (C_PASSENGER_WAIT,   "Storing luggage"),
            ((220, 80, 80),      "Blocked/waiting"),
            (C_PASSENGER_SEATED, "Seated"),
        ]
        for i, (col, lbl) in enumerate(legend):
            pygame.draw.circle(self.screen, col, (px + 18, ly + 22 + i * 20), 7)
            self.screen.blit(self.font_s.render(lbl, True, C_TEXT), (px + 30, ly + 15 + i * 20))

        # Controls hint
        hint = self.font_s.render("Space=pause  R=restart", True, (100, 110, 130))
        self.screen.blit(hint, (px + 10, SCREEN_H - 60))

    def _draw_stats(self):
        if not self.sim:
            return
        px = 770
        sy = 630
        total = len(self.sim.passengers)
        seated = self.sim.seated_count
        pct = seated / total * 100 if total else 0

        self.screen.blit(self.font_b.render("Statistics", True, C_HEADER), (px + 10, sy))
        lines = [
            f"Method:    {self.method}",
            f"Seated:    {seated}/{total}  ({pct:.0f}%)",
            f"Elapsed:   {self.sim.elapsed:.1f}s",
        ]
        if self.sim.done:
            lines.append(f"DONE  {self.sim.total_time:.1f}s")

        for i, line in enumerate(lines):
            color = (100, 230, 100) if ("DONE" in line) else C_TEXT
            self.screen.blit(self.font_s.render(line, True, color), (px + 10, sy + 20 + i * 18))

        # Progress bar
        bar_y = sy + 110
        bar_rect = pygame.Rect(px + 10, bar_y, 180, 12)
        pygame.draw.rect(self.screen, (60, 70, 90), bar_rect, border_radius=4)
        if total:
            fill = pygame.Rect(px + 10, bar_y, int(180 * seated / total), 12)
            pygame.draw.rect(self.screen, C_BTN_ACTIVE, fill, border_radius=4)
        pygame.draw.rect(self.screen, C_HEADER, bar_rect, 1, border_radius=4)


if __name__ == "__main__":
    App().run()
