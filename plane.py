import pygame
import random
import math
import sys
import time
from enum import Enum
from dataclasses import dataclass
from typing import List, Optional, Tuple

# ── Constants ────────────────────────────────────────────────────────────────
SCREEN_W, SCREEN_H = 1200, 800
FPS = 60

# Layout
AISLE_X_LEFT   = 480
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
C_BG               = (30,  30,  40)
C_PLANE_BODY       = (55,  60,  80)
C_SEAT_EMPTY       = (80,  90, 110)
C_SEAT_TAKEN       = (60, 140,  80)
C_AISLE            = (45,  50,  65)
C_PASSENGER_MOVING = (160,  80, 220)
C_PASSENGER_SEATED = ( 80, 200, 120)
C_PASSENGER_WAIT   = (240, 140,  60)
C_TEXT             = (220, 220, 230)
C_HEADER           = (180, 200, 255)
C_BTN              = ( 70,  80, 110)
C_BTN_HOVER        = (100, 115, 160)
C_BTN_ACTIVE       = ( 60, 130, 200)
C_GRID             = ( 50,  55,  70)

GROUP_COLORS = [
    (220,  80,  80),
    (220, 160,  60),
    ( 80, 200, 120),
    ( 80, 160, 220),
    (180,  80, 220),
    (220, 220,  60),
]

METHOD_COLORS = {
    "Front to Back": (220,  80,  80),
    "Back to Front": (220, 160,  60),
    "WILMA":         ( 80, 200, 120),
    "Steffen":       ( 80, 160, 220),
    "Random":        (200,  80, 200),
}

# Graph layout (analysis mode)
GRAPH_L = 90
GRAPH_R = 730
GRAPH_T = 70
GRAPH_B = 690
GRAPH_W = GRAPH_R - GRAPH_L   # 640
GRAPH_H = GRAPH_B - GRAPH_T   # 620

OCCUPANCIES = [i / 10 for i in range(1, 11)]   # 0.1 … 1.0

# ── Seat geometry ─────────────────────────────────────────────────────────────

def seat_pixel(row: int, col: int) -> Tuple[int, int]:
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

def graph_x(occ: float) -> int:
    return GRAPH_L + int((occ - 0.1) / 0.9 * GRAPH_W)

def graph_y(t: float, max_t: float) -> int:
    if max_t == 0:
        return GRAPH_B
    return GRAPH_B - int(t / max_t * GRAPH_H)

# ── Enums / State ─────────────────────────────────────────────────────────────

class PState(Enum):
    QUEUE    = "queue"
    ENTERING = "entering"
    STORING  = "storing"
    BLOCKED  = "blocked"
    SEATED   = "seated"

# ── Passenger ─────────────────────────────────────────────────────────────────

@dataclass
class Passenger:
    pid:   int
    row:   int
    col:   int
    group: int
    color: tuple

    state:       PState = PState.QUEUE
    aisle_row:   float  = float(NUM_ROWS)
    timer:       float  = 0.0
    luggage_time: float = 0.0
    seated_time:  float = 0.0
    px: float = 0.0
    py: float = 0.0

    def target_aisle_row(self) -> float:
        return float(self.row)

# ── Simulation ────────────────────────────────────────────────────────────────

class PlaneSimulation:
    def __init__(self, method: str, capacity: float, compliance: float):
        self.method     = method
        self.capacity   = capacity
        self.compliance = compliance
        self.reset()

    def reset(self):
        self.passengers: List[Passenger] = []
        self.queue:       List[Passenger] = []
        self.seated_count = 0
        self.elapsed      = 0.0
        self.done         = False
        self.total_time   = 0.0
        self._build_passengers()
        self._assign_queue()

    def _build_passengers(self):
        seats = [(r, c) for r in range(NUM_ROWS) for c in range(SEATS_PER_SIDE * 2)]
        random.shuffle(seats)
        n = max(1, int(len(seats) * self.capacity))
        for i, (r, c) in enumerate(seats[:n]):
            p = Passenger(pid=i, row=r, col=c, group=0, color=(160, 80, 220))
            p.luggage_time = LUGGAGE_TIME_BASE + random.random() * LUGGAGE_TIME_RAND
            self.passengers.append(p)

    def _assign_queue(self):
        method = self.method

        def assign_groups():
            if method == "Back to Front":
                for p in self.passengers:
                    p.group = p.row // 5
            elif method == "Front to Back":
                for p in self.passengers:
                    p.group = (NUM_ROWS - 1 - p.row) // 5
            elif method == "WILMA":
                col_order = {0: 0, 5: 0, 1: 1, 4: 1, 2: 2, 3: 2}
                for p in self.passengers:
                    p.group = col_order[p.col]
            elif method == "Steffen":
                col_order = {0: 0, 5: 0, 1: 2, 4: 2, 2: 4, 3: 4}
                for p in self.passengers:
                    p.group = col_order[p.col] + (0 if p.row % 2 == 0 else 1)
            elif method == "Random":
                for p in self.passengers:
                    p.group = 0

        assign_groups()

        def sort_key(p):
            return p.group + random.gauss(0, (1.0 - self.compliance) * 3)

        self.queue = sorted(self.passengers, key=sort_key)
        for i, p in enumerate(self.queue):
            p.px       = float(AISLE_X_CENTER)
            p.py       = float(SCREEN_H - 30 - i * 4)
            p.aisle_row = float(NUM_ROWS + 2)
            p.state    = PState.QUEUE

    def update(self, dt: float):
        if self.done:
            return
        self.elapsed += dt

        if self.queue:
            entrance_clear = all(
                p.aisle_row < NUM_ROWS - 1
                for p in self.passengers
                if p.state in (PState.ENTERING, PState.STORING, PState.BLOCKED)
            )
            if entrance_clear:
                next_p = self.queue.pop(0)
                next_p.state     = PState.ENTERING
                next_p.aisle_row = float(NUM_ROWS - 0.5)

        for p in self.passengers:
            if p.state in (PState.QUEUE, PState.SEATED):
                continue
            if p.state == PState.ENTERING:
                self._update_entering(p, dt)
            elif p.state == PState.STORING:
                self._update_storing(p, dt)
            elif p.state == PState.BLOCKED:
                self._update_blocked(p, dt)

            if p.state != PState.SEATED:
                p.py = float(aisle_y(min(int(p.aisle_row), NUM_ROWS - 1)))
                if p.aisle_row >= NUM_ROWS:
                    p.py = float(SCREEN_H - 60)
                p.px = float(AISLE_X_CENTER)

        if not self.queue and all(p.state == PState.SEATED for p in self.passengers):
            self.done       = True
            self.total_time = self.elapsed

    def _update_entering(self, p: Passenger, dt: float):
        target = float(p.row)

        nearest_ahead_row = None
        for other in self.passengers:
            if other is p or other.state in (PState.QUEUE, PState.SEATED):
                continue
            if other.aisle_row < p.aisle_row:
                if nearest_ahead_row is None or other.aisle_row > nearest_ahead_row:
                    nearest_ahead_row = other.aisle_row

        if nearest_ahead_row is not None:
            effective_target = max(target, nearest_ahead_row + 1.0)
        else:
            effective_target = target

        if p.aisle_row > effective_target + 0.05:
            p.aisle_row = max(effective_target, p.aisle_row - dt / AISLE_STEP_TIME)

        if p.aisle_row <= target + 0.05:
            p.aisle_row = target
            if self._seat_blocked(p):
                p.state = PState.BLOCKED
                p.timer = BLOCKED_WAIT_BASE + random.random() * BLOCKED_WAIT_RAND
            else:
                p.state = PState.STORING
                p.timer = p.luggage_time

    def _seat_blocked(self, p: Passenger) -> bool:
        aisle_col   = 2 if p.col < SEATS_PER_SIDE else 3
        inner_cols  = (list(range(p.col + 1, aisle_col + 1)) if p.col < SEATS_PER_SIDE
                       else list(range(aisle_col, p.col)))
        return any(
            o.row == p.row and o.col in inner_cols and o.state == PState.SEATED
            for o in self.passengers
        )

    def _update_storing(self, p: Passenger, dt: float):
        p.timer -= dt
        if p.timer <= 0:
            p.state = PState.SEATED
            cx, cy  = seat_center(p.row, p.col)
            p.px, p.py = float(cx), float(cy)
            self.seated_count += 1

    def _update_blocked(self, p: Passenger, dt: float):
        p.timer -= dt
        if p.timer <= 0:
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
        self.label    = label
        self.lo, self.hi = lo, hi
        self.value    = value
        self.fmt      = fmt
        self.dragging = False
        self.track    = pygame.Rect(x, y + 18, w, 6)
        self._update_knob()

    def _update_knob(self):
        t = (self.value - self.lo) / (self.hi - self.lo)
        kx = self.x + int(t * self.w)
        self.knob = pygame.Rect(kx - 7, self.y + 12, 14, 18)

    def draw(self, surf, font, hover=False):
        lbl = font.render(f"{self.label}: {self.fmt.format(self.value)}", True, C_HEADER)
        surf.blit(lbl, (self.x, self.y))
        pygame.draw.rect(surf, (60, 70, 90), self.track, border_radius=3)
        t      = (self.value - self.lo) / (self.hi - self.lo)
        filled = pygame.Rect(self.x, self.y + 18, int(t * self.w), 6)
        pygame.draw.rect(surf, C_BTN_ACTIVE, filled, border_radius=3)
        color  = C_BTN_HOVER if (hover or self.dragging) else C_BTN
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
    METHODS = ["Front to Back", "Back to Front", "WILMA", "Steffen", "Random"]

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Plane Boarding Simulation")
        self.clock  = pygame.time.Clock()
        self.font   = pygame.font.SysFont("segoeui", 15)
        self.font_s = pygame.font.SysFont("segoeui", 13)
        self.font_b = pygame.font.SysFont("segoeui", 18, bold=True)

        self.paused = False
        self.method = "Front to Back"
        self.mode   = "sim"   # "sim" | "analysis"

        # Analysis state
        self.analysis_queue:   list = []
        self.analysis_results: dict = {}
        self.analysis_total:   int  = 0
        self.analysis_done:    int  = 0
        self.graph_data:       dict = {}

        self._build_controls(780)
        self.sim: Optional[PlaneSimulation] = None
        self._start_sim()

    # ── Control construction ──────────────────────────────────────────────────

    def _build_controls(self, px: int):
        # Mode tabs
        self.btn_mode_sim      = Button(px,       48, 86, 26, "Simulate")
        self.btn_mode_analysis = Button(px + 94,  48, 86, 26, "Analyse")
        self.btn_mode_sim.active = True

        # Sim-mode controls
        self.method_buttons = []
        for i, m in enumerate(self.METHODS):
            btn = Button(px, 118 + i * 38, 180, 30, m)
            btn.active = (m == self.method)
            self.method_buttons.append(btn)

        self.cap_slider   = Slider(px, 310, 180, "Capacity",   0.1, 1.0, 0.85)
        self.comp_slider  = Slider(px, 360, 180, "Compliance", 0.0, 1.0, 0.90)
        self.speed_slider = Slider(px, 410, 180, "Speed",      0.25, 8.0, 1.0, fmt="{:.2f}x")
        self.btn_start    = Button(px,      468, 86, 34, "Restart")
        self.btn_pause    = Button(px + 94, 468, 86, 34, "Pause")

        # Analysis-mode controls
        self.an_runs_slider = Slider(px, 120, 180, "Runs",       1, 30,  10, fmt="{:.0f}")
        self.an_comp_slider = Slider(px, 175, 180, "Compliance", 0.0, 1.0, 0.90)
        self.btn_run        = Button(px, 233, 180, 34, "Run Analysis")

    # ── Sim helpers ───────────────────────────────────────────────────────────

    def _start_sim(self):
        self.sim = PlaneSimulation(self.method, self.cap_slider.value, self.comp_slider.value)

    # ── Analysis helpers ──────────────────────────────────────────────────────

    def _start_analysis(self):
        n     = max(1, int(self.an_runs_slider.value))
        comp  = self.an_comp_slider.value
        self.analysis_results = {m: {o: [] for o in OCCUPANCIES} for m in self.METHODS}
        self.analysis_queue   = [
            (m, o, comp)
            for m in self.METHODS
            for o in OCCUPANCIES
            for _ in range(n)
        ]
        self.analysis_total = len(self.analysis_queue)
        self.analysis_done  = 0
        self.graph_data     = {}

    def _process_analysis_queue(self, budget_ms: float = 14.0):
        t0 = time.perf_counter()
        while self.analysis_queue:
            if (time.perf_counter() - t0) * 1000 >= budget_ms:
                break
            method, occ, comp = self.analysis_queue.pop(0)
            result = self._run_headless(method, occ, comp)
            self.analysis_results[method][occ].append(result)
            self.analysis_done += 1
        if not self.analysis_queue and self.analysis_done:
            self._compile_graph()

    def _compile_graph(self):
        self.graph_data = {
            m: [
                sum(self.analysis_results[m][o]) / len(self.analysis_results[m][o])
                if self.analysis_results[m][o] else 0
                for o in OCCUPANCIES
            ]
            for m in self.METHODS
        }

    @staticmethod
    def _run_headless(method: str, capacity: float, compliance: float) -> float:
        sim = PlaneSimulation(method, capacity, compliance)
        while not sim.done:
            sim.update(1.0)
        return sim.total_time

    # ── Main loop ─────────────────────────────────────────────────────────────

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

                # Mode tabs (always active)
                if event.type == pygame.MOUSEBUTTONDOWN:
                    if self.btn_mode_sim.hit(event.pos):
                        self.mode = "sim"
                        self.btn_mode_sim.active      = True
                        self.btn_mode_analysis.active = False
                    if self.btn_mode_analysis.hit(event.pos):
                        self.mode = "analysis"
                        self.btn_mode_sim.active      = False
                        self.btn_mode_analysis.active = True

                if self.mode == "sim":
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
                else:
                    self.an_runs_slider.handle_event(event)
                    self.an_comp_slider.handle_event(event)
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        if self.btn_run.hit(event.pos) and not self.analysis_queue:
                            self._start_analysis()

            if self.mode == "sim" and self.sim:
                self.sim.update(dt)
            elif self.mode == "analysis" and self.analysis_queue:
                self._process_analysis_queue()

            self._draw(mouse)
            pygame.display.flip()

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self, mouse):
        self.screen.fill(C_BG)
        if self.mode == "sim":
            self._draw_plane()
            self._draw_passengers()
        else:
            self._draw_graph()
        self._draw_right_panel(mouse)

    # ── Right panel ───────────────────────────────────────────────────────────

    def _draw_right_panel(self, mouse):
        px = 770
        panel = pygame.Rect(px, 40, SCREEN_W - px - 10, SCREEN_H - 60)
        pygame.draw.rect(self.screen, (40, 45, 60), panel, border_radius=10)
        pygame.draw.rect(self.screen, (70, 80, 110), panel, 1, border_radius=10)

        self.btn_mode_sim.draw(self.screen, self.font, self.btn_mode_sim.hit(mouse))
        self.btn_mode_analysis.draw(self.screen, self.font, self.btn_mode_analysis.hit(mouse))

        if self.mode == "sim":
            self._draw_panel_sim(mouse)
        else:
            self._draw_panel_analysis(mouse)

    def _draw_panel_sim(self, mouse):
        px = 780
        self.screen.blit(self.font_b.render("Boarding Method", True, C_HEADER), (px, 84))

        for btn in self.method_buttons:
            btn.draw(self.screen, self.font, btn.hit(mouse))

        self.cap_slider.draw(self.screen, self.font_s)
        self.comp_slider.draw(self.screen, self.font_s)
        self.speed_slider.draw(self.screen, self.font_s)
        self.btn_start.draw(self.screen, self.font, self.btn_start.hit(mouse))
        self.btn_pause.draw(self.screen, self.font, self.btn_pause.hit(mouse))

        # Legend
        ly = 520
        self.screen.blit(self.font_s.render("Legend:", True, C_HEADER), (px, ly))
        for i, (col, lbl) in enumerate([
            (C_PASSENGER_MOVING, "Walking"),
            (C_PASSENGER_WAIT,   "Storing luggage"),
            ((220, 80, 80),      "Blocked/waiting"),
            (C_PASSENGER_SEATED, "Seated"),
        ]):
            pygame.draw.circle(self.screen, col, (px + 8, ly + 22 + i * 20), 7)
            self.screen.blit(self.font_s.render(lbl, True, C_TEXT), (px + 20, ly + 15 + i * 20))

        hint = self.font_s.render("Space=pause  R=restart", True, (100, 110, 130))
        self.screen.blit(hint, (px, SCREEN_H - 58))

        # Stats
        if self.sim:
            self._draw_stats(px)

    def _draw_stats(self, px: int):
        sy     = 634
        total  = len(self.sim.passengers)
        seated = self.sim.seated_count
        pct    = seated / total * 100 if total else 0

        self.screen.blit(self.font_b.render("Statistics", True, C_HEADER), (px, sy))
        lines = [
            f"Method:   {self.method}",
            f"Seated:   {seated}/{total}  ({pct:.0f}%)",
            f"Elapsed:  {self.sim.elapsed:.1f}s",
        ]
        if self.sim.done:
            lines.append(f"DONE  {self.sim.total_time:.1f}s")
        for i, line in enumerate(lines):
            color = (100, 230, 100) if "DONE" in line else C_TEXT
            self.screen.blit(self.font_s.render(line, True, color), (px, sy + 20 + i * 18))

        bar_y    = sy + 112
        bar_rect = pygame.Rect(px, bar_y, 180, 10)
        pygame.draw.rect(self.screen, (60, 70, 90), bar_rect, border_radius=4)
        if total:
            fill = pygame.Rect(px, bar_y, int(180 * seated / total), 10)
            pygame.draw.rect(self.screen, C_BTN_ACTIVE, fill, border_radius=4)
        pygame.draw.rect(self.screen, C_HEADER, bar_rect, 1, border_radius=4)

    def _draw_panel_analysis(self, mouse):
        px = 780
        self.screen.blit(self.font_b.render("Analysis Settings", True, C_HEADER), (px, 84))

        self.an_runs_slider.draw(self.screen, self.font_s)
        self.an_comp_slider.draw(self.screen, self.font_s)

        busy = bool(self.analysis_queue)
        self.btn_run.active = busy
        self.btn_run.draw(self.screen, self.font, self.btn_run.hit(mouse) and not busy)

        # Progress
        py = 282
        if self.analysis_total:
            pct    = self.analysis_done / self.analysis_total
            status = f"Running: {self.analysis_done}/{self.analysis_total}" if busy else "Done!"
            color  = C_PASSENGER_WAIT if busy else (100, 230, 100)
            self.screen.blit(self.font_s.render(status, True, color), (px, py))
            bar = pygame.Rect(px, py + 18, 180, 10)
            pygame.draw.rect(self.screen, (60, 70, 90), bar, border_radius=4)
            fill = pygame.Rect(px, py + 18, int(180 * pct), 10)
            pygame.draw.rect(self.screen, C_BTN_ACTIVE, fill, border_radius=4)
            pygame.draw.rect(self.screen, C_HEADER, bar, 1, border_radius=4)
        elif not self.graph_data:
            self.screen.blit(
                self.font_s.render("Press Run Analysis to start.", True, (120, 130, 150)),
                (px, py),
            )

        # Method colour legend
        ly = 330
        self.screen.blit(self.font_s.render("Methods:", True, C_HEADER), (px, ly))
        for i, m in enumerate(self.METHODS):
            col = METHOD_COLORS[m]
            ey  = ly + 24 + i * 24
            pygame.draw.line(self.screen, col, (px, ey), (px + 22, ey), 3)
            pygame.draw.circle(self.screen, col, (px + 11, ey), 4)
            self.screen.blit(self.font_s.render(m, True, C_TEXT), (px + 28, ey - 7))

    # ── Graph ─────────────────────────────────────────────────────────────────

    def _draw_graph(self):
        # Collect all available time data for axis scaling
        all_times: list = []
        if self.graph_data:
            all_times = [t for ts in self.graph_data.values() for t in ts if t > 0]
        elif self.analysis_results:
            for m_data in self.analysis_results.values():
                for runs in m_data.values():
                    if runs:
                        all_times.append(sum(runs) / len(runs))

        if not all_times and not self.analysis_queue:
            msg = self.font_b.render("Press  'Run Analysis'  to generate data.", True, (80, 90, 110))
            self.screen.blit(msg, msg.get_rect(center=(GRAPH_L + GRAPH_W // 2, GRAPH_T + GRAPH_H // 2)))
            return

        max_t = max(all_times) * 1.12 if all_times else 60.0

        # Graph background
        bg = pygame.Rect(GRAPH_L - 52, GRAPH_T - 28, GRAPH_W + 62, GRAPH_H + 68)
        pygame.draw.rect(self.screen, (33, 36, 50), bg, border_radius=8)

        # Horizontal grid + Y-axis labels (6 lines including 0)
        for i in range(6):
            t_val = max_t * i / 5
            gy    = graph_y(t_val, max_t)
            pygame.draw.line(self.screen, C_GRID, (GRAPH_L, gy), (GRAPH_R, gy), 1)
            lbl = self.font_s.render(f"{t_val:.0f}s", True, (100, 110, 130))
            self.screen.blit(lbl, (GRAPH_L - 46, gy - 7))

        # Vertical grid + X-axis labels
        for occ in OCCUPANCIES:
            gx = graph_x(occ)
            pygame.draw.line(self.screen, C_GRID, (gx, GRAPH_T), (gx, GRAPH_B), 1)
            lbl = self.font_s.render(f"{int(occ * 100)}%", True, (100, 110, 130))
            self.screen.blit(lbl, (gx - 10, GRAPH_B + 8))

        # Axes
        pygame.draw.line(self.screen, C_HEADER, (GRAPH_L, GRAPH_T), (GRAPH_L, GRAPH_B), 2)
        pygame.draw.line(self.screen, C_HEADER, (GRAPH_L, GRAPH_B), (GRAPH_R, GRAPH_B), 2)

        # Axis titles
        x_lbl = self.font_s.render("Occupancy", True, C_HEADER)
        self.screen.blit(x_lbl, (GRAPH_L + GRAPH_W // 2 - x_lbl.get_width() // 2, GRAPH_B + 30))

        y_lbl = pygame.transform.rotate(self.font_s.render("Boarding Time (s)", True, C_HEADER), 90)
        self.screen.blit(y_lbl, (GRAPH_L - 68, GRAPH_T + GRAPH_H // 2 - y_lbl.get_height() // 2))

        # Chart title
        title = self.font_b.render("Boarding Time vs Occupancy", True, C_HEADER)
        self.screen.blit(title, (GRAPH_L + GRAPH_W // 2 - title.get_width() // 2, GRAPH_T - 44))

        # Decide which data source to draw from
        if self.graph_data:
            source = {m: list(zip(OCCUPANCIES, ts)) for m, ts in self.graph_data.items()}
        else:
            # In-progress: show averages of runs collected so far
            source = {}
            for m in self.METHODS:
                pts = []
                for occ in OCCUPANCIES:
                    runs = self.analysis_results.get(m, {}).get(occ, [])
                    if runs:
                        pts.append((occ, sum(runs) / len(runs)))
                source[m] = pts

        for method, pts in source.items():
            if not pts:
                continue
            col    = METHOD_COLORS[method]
            pixels = [(graph_x(occ), graph_y(t, max_t)) for occ, t in pts if t > 0]
            if len(pixels) >= 2:
                pygame.draw.lines(self.screen, col, False, pixels, 2)
            for px_pt in pixels:
                pygame.draw.circle(self.screen, col, px_pt, 5)
                pygame.draw.circle(self.screen, C_BG, px_pt, 2)

    # ── Plane drawing (sim mode) ──────────────────────────────────────────────

    def _draw_plane(self):
        plane_rect = pygame.Rect(
            AISLE_X_LEFT - SEATS_PER_SIDE * (SEAT_W + SEAT_GAP) - 10,
            FIRST_ROW_Y - 15,
            AISLE_X_RIGHT - AISLE_X_LEFT + SEATS_PER_SIDE * (SEAT_W + SEAT_GAP) * 2 + 20,
            NUM_ROWS * ROW_HEIGHT + 30,
        )
        pygame.draw.rect(self.screen, C_PLANE_BODY, plane_rect, border_radius=12)

        aisle_rect = pygame.Rect(AISLE_X_LEFT, FIRST_ROW_Y - 10,
                                 AISLE_X_RIGHT - AISLE_X_LEFT, NUM_ROWS * ROW_HEIGHT + 20)
        pygame.draw.rect(self.screen, C_AISLE, aisle_rect)

        for row in range(NUM_ROWS):
            rl = self.font_s.render(str(row + 1), True, (120, 130, 150))
            self.screen.blit(rl, (AISLE_X_CENTER - 8, FIRST_ROW_Y + row * ROW_HEIGHT + 4))
            for col in range(SEATS_PER_SIDE * 2):
                sx, sy = seat_pixel(row, col)
                color  = C_SEAT_EMPTY
                for p in (self.sim.passengers if self.sim else []):
                    if p.row == row and p.col == col and p.state == PState.SEATED:
                        color = C_SEAT_TAKEN
                        break
                pygame.draw.rect(self.screen, color, (sx, sy, SEAT_W, SEAT_H), border_radius=4)

        tip_x = AISLE_X_CENTER
        top_y = FIRST_ROW_Y - 30
        pygame.draw.polygon(self.screen, (100, 120, 160),
                            [(tip_x, top_y), (tip_x - 12, top_y + 20), (tip_x + 12, top_y + 20)])
        self.screen.blit(self.font_s.render("BACK", True, (140, 160, 200)), (tip_x - 20, top_y - 16))

        ent_y = FIRST_ROW_Y + NUM_ROWS * ROW_HEIGHT + 18
        pygame.draw.polygon(self.screen, (80, 160, 220),
                            [(tip_x, ent_y - 10), (tip_x - 10, ent_y + 8), (tip_x + 10, ent_y + 8)])
        self.screen.blit(self.font_s.render("BOARD", True, (80, 160, 220)), (tip_x - 18, ent_y + 10))

    def _draw_passengers(self):
        if not self.sim:
            return
        queue_x = AISLE_X_CENTER
        for i, p in enumerate(self.sim.queue):
            qy = SCREEN_H - 40 - i * 5
            if qy < FIRST_ROW_Y + NUM_ROWS * ROW_HEIGHT + 40:
                break
            pygame.draw.circle(self.screen, p.color, (queue_x, qy), 4)

        for p in self.sim.passengers:
            if p.state == PState.QUEUE:
                continue
            if p.state == PState.SEATED:
                pygame.draw.circle(self.screen, C_PASSENGER_SEATED,
                                   (int(p.px), int(p.py)), PASSENGER_R - 2)
            elif p.state == PState.STORING:
                pygame.draw.circle(self.screen, C_PASSENGER_WAIT,
                                   (int(p.px), int(p.py)), PASSENGER_R)
                if p.luggage_time > 0:
                    frac     = 1.0 - p.timer / p.luggage_time
                    arc_rect = pygame.Rect(int(p.px) - PASSENGER_R, int(p.py) - PASSENGER_R,
                                          PASSENGER_R * 2, PASSENGER_R * 2)
                    try:
                        pygame.draw.arc(self.screen, (255, 255, 100), arc_rect,
                                        math.pi / 2, math.pi / 2 + frac * 2 * math.pi, 3)
                    except Exception:
                        pass
            elif p.state == PState.BLOCKED:
                pygame.draw.circle(self.screen, (220, 80, 80),
                                   (int(p.px), int(p.py)), PASSENGER_R)
            else:
                pygame.draw.circle(self.screen, p.color,
                                   (int(p.px), int(p.py)), PASSENGER_R)

            pygame.draw.circle(self.screen, GROUP_COLORS[p.group % len(GROUP_COLORS)],
                               (int(p.px) + PASSENGER_R - 2, int(p.py) - PASSENGER_R + 2), 3)


if __name__ == "__main__":
    App().run()
