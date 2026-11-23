#!/usr/bin/env python3
"""
build_part1.py

One self-contained build script for Part 1 of the series
"Football Math with RoboCup 2D": "Football in 100 Milliseconds".

What it does, in this order:
  1. Runs sanity checks. If one fails, it stops and writes nothing.
  2. Draws every figure as PNG (1600 px wide) into OUT_DIR/figures/.
  3. Computes every number that appears in the article text.
  4. Writes the article twice:
       OUT_DIR/part1_devto.md   (dev.to, KaTeX liquid tags, absolute image URLs)
       OUT_DIR/part1_github.md  (GitHub, $...$ math, relative image paths)

All demos are TOY models that use equations described in the source report.
This script does NOT run rcssserver.

Needs: Python 3.10+, numpy, matplotlib.
"""

import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt
from matplotlib.patches import (Rectangle, Circle, Wedge,
                                FancyArrowPatch, FancyBboxPatch)

# =====================================================================
# CONFIG (edit these)
# =====================================================================
TARGET_FILES = {"devto": "part1_devto.md", "github": "part1_github.md"}
BASE_URL = "https://raw.githubusercontent.com/USERNAME/REPO/main/part1/figures"
OUT_DIR = "part1"
SERIES = "Football Math with RoboCup 2D"
TAGS = ["robotics", "python", "math", "beginners"]
SEED = 7
PUBLISHED = False

DESCRIPTION = ("How the RoboCup 2D soccer simulator works, and why every "
               "virtual player only sees part of the pitch.")

# =====================================================================
# VALUES FROM THE SOURCE REPORT (manual / rcssserver v19.0.0, as stated there)
# Check each one before publishing.
# =====================================================================
CYCLE_MS = 100                    # nominal cycle length (manual, section 4.3)
VIEW_MODES = {                    # (width in degrees, cycles per new picture)
    "narrow": (60, 1),
    "normal": (120, 2),
    "wide": (180, 3),
}
SYNC_DEFAULT_FROM = 18            # synchronous vision is the default from v18
SAY_CHARS = 10                    # say message: max characters
SAY_RANGE_M = 50                  # say message: default range in metres
N_AGENTS = 22                     # independent agents in a match
R_MOVABLE = 0.0125                # Gaussian vision rate, ball and players
R_LANDMARK = 0.00125              # Gaussian vision rate, landmarks
SERVER_VERSION = "19.0.0"
RELEASE_DATE = "25 March 2024"
BACK_DASH_RATE = 0.7              # v19 tag value (manual table differs)
EFFORT_DEC = 0.005                # v19 tag value (manual table differs)
BALL_DECAY = 0.94                 # v19 baseline ball decay (used in teaser)

# =====================================================================
# TOY CHOICES (NOT from the report; never quote them as facts)
# =====================================================================
PITCH_LENGTH = 100.0              # drawing size only
PITCH_WIDTH = 64.0                # drawing size only
VIEW_RADIUS_DRAW = 40.0           # cone radius, only for drawing/testing
MEMORY_KEEP_PROB = 0.5            # toy: chance to still remember an unseen player
MEMORY_DRIFT_M = 3.0              # toy: how far an old memory has drifted
D_NEAR, D_FAR = 10.0, 40.0        # distances used as examples in the text
N_ROUNDTRIP = 10_000              # random tests for the inverse formula
N_MONTE_CARLO = 200_000           # samples for the noise check
TRY_MODE = (240, 4)               # "invent a view mode" exercise

# =====================================================================
# STYLE AND DRAWING HELPERS (Okabe-Ito colorblind-safe palette)
# =====================================================================
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
VERMILLION = "#D55E00"
SKY = "#56B4E9"
GREY = "#8C8C8C"
BLACK = "#000000"
TEAM_US = BLUE
TEAM_THEM = ORANGE
GRASS = "#F2F2F2"
LINES = "#555555"

DPI = 200
FIG_WIDTH_IN = 8.0                # 8 in x 200 dpi = 1600 px
FIG_WIDTH_PX = int(FIG_WIDTH_IN * DPI)


def set_style():
    """Big fonts and a clean look, the same in every part."""
    plt.rcParams.update({
        "font.size": 15,
        "axes.titlesize": 16,
        "axes.labelsize": 15,
        "xtick.labelsize": 13,
        "ytick.labelsize": 13,
        "legend.fontsize": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.dpi": DPI,
    })


def new_figure(height_in=5.0, nrows=1, ncols=1, **kw):
    """Make a figure that is always 1600 px wide."""
    return plt.subplots(nrows, ncols, figsize=(FIG_WIDTH_IN, height_in),
                        layout="constrained", **kw)


def save_figure(fig, path):
    """Save as PNG with a white background, then close the figure."""
    fig.savefig(path, dpi=DPI, facecolor="white")
    plt.close(fig)
    print(f"  saved {path}")


def draw_pitch(ax, title=None):
    """Draw a schematic pitch centred on (0, 0). Toy sizes."""
    L, W = PITCH_LENGTH, PITCH_WIDTH
    ax.add_patch(Rectangle((-L / 2, -W / 2), L, W, facecolor=GRASS,
                           edgecolor=LINES, lw=2, zorder=0))
    ax.plot([0, 0], [-W / 2, W / 2], color=LINES, lw=1.5, zorder=1)
    ax.add_patch(Circle((0, 0), 9.0, fill=False, edgecolor=LINES, lw=1.5, zorder=1))
    for side in (-1, 1):
        x_line = side * L / 2
        box_depth, box_width = 16.0, 40.0
        x0 = x_line if side == -1 else x_line - box_depth
        ax.add_patch(Rectangle((x0, -box_width / 2), box_depth, box_width,
                               fill=False, edgecolor=LINES, lw=1.5, zorder=1))
        goal_depth, goal_width = 2.0, 14.0
        gx = x_line - goal_depth if side == -1 else x_line
        ax.add_patch(Rectangle((gx, -goal_width / 2), goal_depth, goal_width,
                               facecolor=LINES, edgecolor=LINES, zorder=1))
    margin = 4.0
    ax.set_aspect("equal")
    ax.set_xlim(-L / 2 - margin, L / 2 + margin)
    ax.set_ylim(-W / 2 - margin, W / 2 + margin)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    if title:
        ax.set_title(title)


def draw_player(ax, x, y, color, label=None, heading_deg=None,
                size=1.6, hollow=False, alpha=1.0):
    """Draw a player as a circle, with an optional heading line and label."""
    face = "white" if hollow else color
    ax.add_patch(Circle((x, y), size, facecolor=face, edgecolor=color,
                        lw=2.5, alpha=alpha, zorder=5))
    if heading_deg is not None:
        h = np.radians(heading_deg)
        ax.plot([x, x + 2.0 * size * np.cos(h)], [y, y + 2.0 * size * np.sin(h)],
                color=color, lw=3, alpha=alpha, zorder=6)
    if label:
        ax.text(x, y, label, ha="center", va="center", fontsize=10,
                fontweight="bold", color=color if hollow else "white",
                alpha=alpha, zorder=7)


def draw_ball(ax, x, y, size=1.1):
    """Draw the ball as a white circle with a black centre."""
    ax.add_patch(Circle((x, y), size, facecolor="white", edgecolor=BLACK,
                        lw=2.5, zorder=8))
    ax.add_patch(Circle((x, y), size * 0.45, facecolor=BLACK,
                        edgecolor=BLACK, zorder=9))


def draw_arrow(ax, start, end, color=BLACK, lw=2.5, ls="-", zorder=4):
    """Draw an arrow from start to end."""
    arrow = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=18,
                            color=color, lw=lw, linestyle=ls, zorder=zorder)
    ax.add_patch(arrow)
    return arrow


def draw_view_cone(ax, x, y, heading_deg, width_deg, radius, color=SKY, alpha=0.30):
    """Draw a view cone (a pie slice) centred on the heading."""
    ax.add_patch(Wedge((x, y), radius, heading_deg - width_deg / 2,
                       heading_deg + width_deg / 2, facecolor=color,
                       edgecolor=color, alpha=alpha, zorder=2))


def in_view_cone(px, py, x, y, heading_deg, width_deg, radius):
    """True if point(s) (px, py) are inside the cone. Works with arrays."""
    dx, dy = np.asarray(px) - x, np.asarray(py) - y
    dist = np.hypot(dx, dy)
    ang = (np.degrees(np.arctan2(dy, dx)) - heading_deg + 180.0) % 360.0 - 180.0
    return (dist <= radius) & (np.abs(ang) <= width_deg / 2.0)


# =====================================================================
# MATH HELPERS
# =====================================================================
def wrap_deg(a):
    """Wrap angles to the range (-180, 180]."""
    a = (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0
    return np.where(a == -180.0, 180.0, a)


def distance_and_bearing(rel_x, rel_y, body_deg, head_deg):
    """[Simulator rule] distance and relative bearing of an object."""
    d = np.hypot(rel_x, rel_y)
    bearing = wrap_deg(np.degrees(np.arctan2(rel_y, rel_x)) - (body_deg + head_deg))
    return d, bearing


def back_to_xy(d, bearing, body_deg, head_deg):
    """[Derived here] turn distance and bearing back into a relative x, y."""
    ang = np.radians(bearing + body_deg + head_deg)
    return d * np.cos(ang), d * np.sin(ang)


def gaussian_seen_distance(d, f, r_d, r_f, rng, size=None):
    """[Simulator rule, v19 opt-in] D = max(0, Z), Z ~ N(d, sigma^2)."""
    sigma = r_d * d + r_f * f
    return np.maximum(0.0, rng.normal(d, sigma, size=size))


def fmt(x):
    """Short number format for the text: 0.25, 1, 0.0125, 10."""
    return f"{x:.3g}"


# =====================================================================
# LATEX (raw strings, KaTeX-safe, no "{{" anywhere)
# =====================================================================
def build_latex():
    """Return dict: placeholder key -> LaTeX string. Numbers come from CONFIG."""
    lx = {}
    cps = fmt(1000 / CYCLE_MS)
    lx["EQ_CPS"] = (r"\frac{1000\ \mathrm{ms}}{" + str(CYCLE_MS) + r"\ \mathrm{ms}} = "
                    + cps + r"\ \text{cycles per second}")
    fracs = [r"\frac{" + str(w) + r"^\circ}{" + str(k) + "}"
             for (w, k) in VIEW_MODES.values()]
    rate = fmt(list(VIEW_MODES.values())[0][0] / list(VIEW_MODES.values())[0][1])
    lx["EQ_RATE"] = " = ".join(fracs) + " = " + rate + r"^\circ\ \text{per cycle}"
    lx["EQ_DISTANCE"] = r"d = \sqrt{r_x^2 + r_y^2}"
    lx["EQ_BEARING"] = (r"\theta = \operatorname{atan2}(r_y, r_x) - "
                        r"(\phi_{\mathrm{body}} + \phi_{\mathrm{head}})")
    lx["EQ_INVERSE"] = (r"r_x = d \cdot \cos(\theta + \phi_{\mathrm{body}} + \phi_{\mathrm{head}}), \quad "
                        r"r_y = d \cdot \sin(\theta + \phi_{\mathrm{body}} + \phi_{\mathrm{head}})")
    lx["EQ_GAUSS"] = r"Z \sim \mathcal{N}(d, \sigma^2), \qquad \sigma = r_d \cdot d + r_f \cdot f"
    lx["EQ_CLIP"] = r"D = \max(0, Z)"
    lx["EQ_SIGMA_TOY"] = (r"\sigma = (r_d + r_f) \cdot d = " + fmt(2 * R_MOVABLE)
                          + r" \cdot d")
    # Short inline formulas
    lx["M_THETA"] = r"\theta"
    lx["M_D"] = r"d"
    lx["M_R"] = r"r = (r_x, r_y)"
    lx["M_ATAN"] = r"\operatorname{atan2}(y, x)"
    lx["M_PHIB"] = r"\phi_{\mathrm{body}}"
    lx["M_PHIH"] = r"\phi_{\mathrm{head}}"
    lx["M_SIGMA"] = r"\sigma"
    lx["M_F"] = r"f"
    lx["M_RD"] = r"r_d"
    lx["M_RF"] = r"r_f"
    lx["M_DEG"] = rate + r"^\circ"
    lx["M_SUM_ANGLE"] = r"\theta + \phi_{\mathrm{body}} + \phi_{\mathrm{head}} = \operatorname{atan2}(r_y, r_x)"
    lx["M_COMPONENTS"] = r"(d \cdot \cos a,\ d \cdot \sin a)"
    return lx


def math_block(latex, target):
    """Display math for dev.to (KaTeX liquid tag) or GitHub ($$ ... $$)."""
    if target == "devto":
        return "{% katex %}\n" + latex + "\n{% endkatex %}"
    return "$$\n" + latex + "\n$$"


def math_inline(latex, target):
    """Inline math for dev.to or GitHub."""
    if target == "devto":
        return "{% katex inline %}" + latex + "{% endkatex %}"
    return "$" + latex + "$"


# =====================================================================
# FIGURES (one function per figure)
# =====================================================================
def fig_loop(path):
    """Figure 1: one cycle, server in the middle, clients on both sides."""
    fig, ax = new_figure(height_in=5.2)
    ax.set_xlim(0, 10)
    ax.set_ylim(-0.3, 6.3)
    ax.axis("off")

    def box(x, y, w, h, text, color, fs=13):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08",
                                    facecolor="white", edgecolor=color, lw=3))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs)

    box(3.6, 2.1, 2.8, 1.8, "rcssserver\nhidden true state\nrules + physics", BLACK, fs=14)
    for y in (4.8, 2.55, 0.3):
        box(0.1, y, 2.4, 0.9, "our client\nworld model → decide", TEAM_US, fs=12)
        box(7.5, y, 2.4, 0.9, "their client\nworld model → decide", TEAM_THEM, fs=12)
        cy = y + 0.45
        for client_edge, server_edge in ((2.6, 3.5), (7.4, 6.5)):
            # what the client senses: server -> client (dashed grey)
            draw_arrow(ax, (server_edge, 3.15), (client_edge, cy + 0.15), color=GREY, ls="--")
            # commands: client -> server (solid black)
            draw_arrow(ax, (client_edge, cy - 0.15), (server_edge, 2.85), color=BLACK)
    ax.text(5, 0.45, "dashed = what clients sense\nsolid = commands they send",
            ha="center", va="center", fontsize=12)
    n_team = N_AGENTS // 2
    ax.set_title(f"One cycle (nominally {CYCLE_MS} ms): sense → think → act\n"
                 f"{n_team} clients per team; only 3 drawn per side", fontsize=14)
    save_figure(fig, path)


def fig_view_modes(path):
    """Figure 2: the same player with the three view widths."""
    rng = np.random.default_rng(SEED + 1)
    others = np.column_stack([rng.uniform(-45, 45, 16), rng.uniform(-28, 28, 16)])
    me, heading = (-12.0, -2.0), 10.0
    fig, axes = new_figure(height_in=3.6, ncols=3)
    for ax, (name, (width, k)) in zip(axes, VIEW_MODES.items()):
        draw_pitch(ax)
        draw_view_cone(ax, me[0], me[1], heading, width, VIEW_RADIUS_DRAW)
        inside = in_view_cone(others[:, 0], others[:, 1], me[0], me[1],
                              heading, width, VIEW_RADIUS_DRAW)
        for (px, py), ins in zip(others, inside):
            if ins:
                draw_player(ax, px, py, TEAM_THEM, size=2.0)
            else:
                draw_player(ax, px, py, GREY, size=2.0, hollow=True, alpha=0.7)
        draw_player(ax, me[0], me[1], TEAM_US, heading_deg=heading, size=2.4)
        plural = "s" if k > 1 else ""
        ax.set_title(f"{name.capitalize()} {width}°\nnew picture every {k} cycle{plural}",
                     fontsize=13)
        ax.set_xlabel(f"sees {int(inside.sum())} of {len(others)}", fontsize=13)
    save_figure(fig, path)


def fig_timeline(path):
    """Figure 3: when pictures arrive, and how old the newest one is."""
    cycles = np.arange(0, 13)
    colors = {"narrow": BLUE, "normal": GREEN, "wide": VERMILLION}
    styles = {"narrow": "-", "normal": "--", "wide": ":"}
    fig, (ax1, ax2) = new_figure(height_in=6.0, nrows=2, sharex=True)
    names = list(VIEW_MODES)
    for row, name in enumerate(names):
        width, k = VIEW_MODES[name]
        arrivals = cycles[cycles % k == 0]          # toy timing
        ax1.scatter(arrivals, np.full(arrivals.shape, len(names) - 1 - row),
                    marker="v", s=160, color=colors[name], zorder=3)
        ages_ms = (cycles % k) * CYCLE_MS
        ax2.step(cycles, ages_ms, where="post", color=colors[name],
                 ls=styles[name], lw=3, label=f"{name} {width}°")
    ax1.set_yticks(list(range(len(names) - 1, -1, -1)))
    ax1.set_yticklabels([f"{n} {VIEW_MODES[n][0]}°" for n in names])
    ax1.set_ylim(-0.6, len(names) - 0.4)
    ax1.set_title("When does a new picture arrive? (toy timing)")
    max_age = max((k - 1) * CYCLE_MS for (_, k) in VIEW_MODES.values())
    ax2.set_ylabel("Age of newest\npicture (ms)")
    ax2.set_xlabel(f"Cycle number (1 cycle ≈ {CYCLE_MS} ms)")
    ax2.set_ylim(-10, max_age * 1.65)
    ax2.legend(loc="upper center", ncol=3, frameon=False)
    save_figure(fig, path)


def fig_noise(path):
    """Figure 4: toy Gaussian vision noise grows with distance."""
    rng = np.random.default_rng(SEED + 2)
    d_true = rng.uniform(0, 50, 1500)
    d_seen = gaussian_seen_distance(d_true, d_true, R_MOVABLE, R_MOVABLE, rng)  # toy f = d
    grid = np.linspace(0, 50, 200)
    fig, axes = new_figure(height_in=4.6, ncols=2)

    ax = axes[0]
    ax.scatter(d_true, d_seen - d_true, s=8, alpha=0.4, color=BLUE)
    sig = 2 * R_MOVABLE * grid
    ax.plot(grid, sig, color=VERMILLION, lw=3, label="±σ")
    ax.plot(grid, -sig, color=VERMILLION, lw=3)
    ax.set_xlabel("True distance d (m)")
    ax.set_ylabel("Seen − true (m)")
    ax.set_title("Ball or player\n(toy: f = d)")
    ax.legend(loc="upper left", frameon=False)

    ax = axes[1]
    ax.plot(grid, 2 * R_MOVABLE * grid, color=BLUE, lw=3, label="ball / players")
    ax.plot(grid, 2 * R_LANDMARK * grid, color=GREEN, lw=3, ls="--", label="landmarks")
    ax.set_xlabel("True distance d (m)")
    ax.set_ylabel("Noise spread σ (m)")
    ax.set_title("Spread grows\nwith distance")
    ax.legend(loc="upper left", frameon=False)
    save_figure(fig, path)


def fig_hidden_vs_belief(path):
    """Figure 5: the true state vs one player's toy world model."""
    rng = np.random.default_rng(SEED + 3)
    us = np.column_stack([rng.uniform(-45, 5, 10), rng.uniform(-28, 28, 10)])
    them = np.column_stack([rng.uniform(-5, 45, 11), rng.uniform(-28, 28, 11)])
    me = np.array([-8.0, -4.0])
    body, head, width = 15.0, 0.0, 120.0
    view_dir = body + head
    ball = me + 14.0 * np.array([np.cos(np.radians(view_dir)),
                                 np.sin(np.radians(view_dir))])

    fig, (axL, axR) = new_figure(height_in=3.9, ncols=2)

    # Left: the truth
    draw_pitch(axL, title="Hidden state\n(what the server knows)")
    for p in us:
        draw_player(axL, p[0], p[1], TEAM_US, size=2.0)
    for p in them:
        draw_player(axL, p[0], p[1], TEAM_THEM, size=2.0)
    draw_player(axL, me[0], me[1], TEAM_US, label="7", heading_deg=view_dir, size=2.4)
    draw_ball(axL, ball[0], ball[1])
    axL.set_xlabel(f"all {N_AGENTS} players + ball", fontsize=12)

    # Right: player 7's belief (toy)
    draw_pitch(axR, title="World model\n(what player 7 believes)")
    draw_view_cone(axR, me[0], me[1], view_dir, width, VIEW_RADIUS_DRAW)
    counts = {"seen": 0, "old": 0, "unknown": 0}

    def believe(p, color):
        if in_view_cone(p[0], p[1], me[0], me[1], view_dir, width, VIEW_RADIUS_DRAW):
            d, b = distance_and_bearing(p[0] - me[0], p[1] - me[1], body, head)
            d_seen = gaussian_seen_distance(d, d, R_MOVABLE, R_MOVABLE, rng)
            x, y = back_to_xy(d_seen, b, body, head)       # toy: bearing kept exact
            draw_player(axR, me[0] + float(x), me[1] + float(y), color, size=2.0)
            counts["seen"] += 1
        elif rng.random() < MEMORY_KEEP_PROB:
            drift = rng.normal(0.0, MEMORY_DRIFT_M, 2)     # toy: old memory drifted
            draw_player(axR, p[0] + drift[0], p[1] + drift[1], color,
                        size=2.0, hollow=True, alpha=0.6)
            counts["old"] += 1
        else:
            counts["unknown"] += 1

    for p in us:
        believe(p, TEAM_US)
    for p in them:
        believe(p, TEAM_THEM)
    db, bb = distance_and_bearing(ball[0] - me[0], ball[1] - me[1], body, head)
    xb, yb = back_to_xy(gaussian_seen_distance(db, db, R_MOVABLE, R_MOVABLE, rng),
                        bb, body, head)
    draw_ball(axR, me[0] + float(xb), me[1] + float(yb))
    draw_player(axR, me[0], me[1], TEAM_US, label="7", heading_deg=view_dir, size=2.4)
    axR.set_xlabel(f"seen now: {counts['seen']}   old: {counts['old']}   "
                   f"unknown: {counts['unknown']}", fontsize=12)
    save_figure(fig, path)


FIGURES = [
    {"key": "FIG_LOOP", "file": "fig1_1_loop.png", "func": fig_loop,
     "alt": "Diagram with the server box in the middle and client boxes on both sides. "
            "Dashed arrows go from the server to the clients, solid arrows go back as commands.",
     "caption": "Figure 1. One cycle: the server sends what each player senses, "
                "each client thinks, and each client sends commands back."},
    {"key": "FIG_VIEW", "file": "fig1_2_view_modes.png", "func": fig_view_modes,
     "alt": "Three small pitches with a light-blue view cone of 60, 120 and 180 degrees "
            "from the same player. More opponents are inside the wider cones.",
     "caption": "Figure 2. The same player in the three view modes. Coloured dots are "
                "inside the cone. Hollow grey dots are not seen. Toy cone radius."},
    {"key": "FIG_TIMELINE", "file": "fig1_3_view_timeline.png", "func": fig_timeline,
     "alt": "Top: triangle markers every cycle for narrow, every 2 cycles for normal, every "
            "3 cycles for wide. Bottom: step lines showing the age of the newest picture.",
     "caption": "Figure 3. When new pictures arrive (top) and how old the newest picture "
                "is (bottom). Toy timing."},
    {"key": "FIG_NOISE", "file": "fig1_4_vision_noise.png", "func": fig_noise,
     "alt": "Left: a scatter of distance errors that fans out as distance grows, with red "
            "plus and minus sigma lines. Right: sigma against distance, steep for ball and "
            "players, almost flat for landmarks.",
     "caption": "Figure 4. Toy Gaussian vision. Errors grow with distance. Landmarks are "
                "much less noisy than the ball and players."},
    {"key": "FIG_BELIEF", "file": "fig1_5_hidden_vs_belief.png", "func": fig_hidden_vs_belief,
     "alt": "Two pitches. Left: all players and the ball. Right: only players inside a view "
            "cone are solid, some are faded old memories, and others are missing.",
     "caption": "Figure 5. Left: what the server knows. Right: what player 7 believes. "
                "Toy model: memories, drift and exact bearings are my simplifications."},
]

# =====================================================================
# SANITY CHECKS (run first; any failure stops the build)
# =====================================================================
CHECK_LOG = []


def check(condition, message):
    """Like assert, but also works with python -O, and logs what passed."""
    if not condition:
        raise AssertionError(message)
    CHECK_LOG.append(message)


def run_sanity_checks():
    rng = np.random.default_rng(SEED + 10)
    results = {}

    # Config checks
    check(0 < len(TAGS) <= 4, "dev.to: between 1 and 4 tags")
    check(all(re.fullmatch(r"[a-z0-9]+", t) for t in TAGS),
          "dev.to: tags use only lowercase letters and digits")
    check(BASE_URL.startswith("https://") and not BASE_URL.endswith("/"),
          "BASE_URL is https and has no trailing slash")
    check(len(TARGET_FILES) > 0 and set(TARGET_FILES) <= {"devto", "github"},
          "TARGET_FILES only contains 'devto' and/or 'github'")

    # LaTeX must be safe for dev.to liquid tags
    for key, latex in build_latex().items():
        check("{{" not in latex and "{%" not in latex,
              f"LaTeX {key}: no '{{{{' or '{{%' (would break dev.to liquid)")

    # Figure metadata safe for Markdown
    names = [f["file"] for f in FIGURES]
    check(len(names) == len(set(names)), "figure file names are unique")
    for f in FIGURES:
        check("[" not in f["alt"] and "]" not in f["alt"] and "*" not in f["caption"],
              f"{f['file']}: alt text and caption are Markdown-safe")

    # 1. Cycles per second
    cps = 1000 / CYCLE_MS
    check(abs(cps - round(cps)) < 1e-12, f"1000 ms / {CYCLE_MS} ms = {fmt(cps)} cycles per second")
    results["cps"] = cps

    # 2. Same degrees per cycle for every view mode
    rates = [w / k for (w, k) in VIEW_MODES.values()]
    check(max(rates) - min(rates) < 1e-12,
          f"all view modes give {fmt(rates[0])} degrees per cycle on average")
    results["rate"] = rates[0]

    # 3. Distance/bearing round trip
    rel = rng.uniform(-50, 50, size=(N_ROUNDTRIP, 2))
    body = rng.uniform(-180, 180, N_ROUNDTRIP)
    head = rng.uniform(-90, 90, N_ROUNDTRIP)
    d, b = distance_and_bearing(rel[:, 0], rel[:, 1], body, head)
    x, y = back_to_xy(d, b, body, head)
    rt_err = float(np.max(np.hypot(x - rel[:, 0], y - rel[:, 1])))
    check(rt_err < 1e-9, f"inverse formula: largest error {rt_err:.1e} m over {N_ROUNDTRIP:,} tests")
    check(bool(np.all(b > -180.0) and np.all(b <= 180.0)), "bearings are wrapped to (-180, 180]")
    results["rt_err"] = rt_err

    # 4. Gaussian vision spread matches sigma = (r_d + r_f) d with toy f = d
    measured = {}
    for dist in (D_NEAR, 20.0, D_FAR):
        s = gaussian_seen_distance(np.full(N_MONTE_CARLO, dist), dist,
                                   R_MOVABLE, R_MOVABLE, rng)
        expected = 2 * R_MOVABLE * dist
        rel_err = abs(s.std() - expected) / expected
        check(rel_err < 0.02, f"noise at {fmt(dist)} m: sigma {expected:.3f} expected, "
                              f"{s.std():.3f} measured ({rel_err:.2%} off)")
        measured[dist] = float(s.std())
    results["sigma_far_measured"] = measured[D_FAR]

    # 5. Seen distance never negative
    s = gaussian_seen_distance(np.full(N_MONTE_CARLO, 0.05), 0.05, R_MOVABLE, R_MOVABLE, rng)
    check(float(s.min()) >= 0.0, "seen distance is never negative (max(0, Z))")

    # 6. Toy timeline: newest picture at most (k - 1) cycles old
    for name, (w, k) in VIEW_MODES.items():
        check(int((np.arange(300) % k).max()) == k - 1,
              f"{name}: newest picture at most {(k - 1) * CYCLE_MS} ms old (toy timing)")

    # 7. Exercise mode is also fair
    tw, tk = TRY_MODE
    check(abs(tw / tk - rates[0]) < 1e-12, f"exercise mode {tw} deg / {tk} cycles is also fair")
    return results


def check_figure_files(fig_dir):
    """After drawing: every PNG exists and is 1600 px wide."""
    for f in FIGURES:
        path = fig_dir / f["file"]
        check(path.exists(), f"{f['file']} exists")
        width = plt.imread(str(path)).shape[1]
        check(width == FIG_WIDTH_PX, f"{f['file']} is {FIG_WIDTH_PX} px wide")


# =====================================================================
# NUMBERS FOR THE TEXT (every number in the article comes from here)
# =====================================================================
def compute_numbers(res):
    v = {}
    v["CYCLE_MS"] = str(CYCLE_MS)
    v["CYCLES_PER_SEC"] = fmt(res["cps"])
    v["N_AGENTS"] = str(N_AGENTS)
    v["SAY_CHARS"] = str(SAY_CHARS)
    v["SAY_RANGE_M"] = str(SAY_RANGE_M)
    v["SYNC_DEFAULT_FROM"] = str(SYNC_DEFAULT_FROM)
    for name, (w, k) in VIEW_MODES.items():
        up = name.upper()
        v["W_" + up] = str(w)
        v["K_" + up] = str(k)
        v["GAP_" + up + "_MS"] = str(k * CYCLE_MS)
        v["AGE_" + up + "_MS"] = str((k - 1) * CYCLE_MS)
    v["RATE_ALL"] = fmt(res["rate"])
    v["N_RT"] = f"{N_ROUNDTRIP:,}"
    v["RT_ERR"] = f"{res['rt_err']:.1e}"
    v["R_MOV"] = fmt(R_MOVABLE)
    v["R_LAND"] = fmt(R_LANDMARK)
    v["R_SUM"] = fmt(2 * R_MOVABLE)
    v["D_NEAR"] = fmt(D_NEAR)
    v["D_FAR"] = fmt(D_FAR)
    v["SIGMA_NEAR"] = fmt(2 * R_MOVABLE * D_NEAR)
    v["SIGMA_FAR"] = fmt(2 * R_MOVABLE * D_FAR)
    v["SIGMA_LAND_NEAR"] = fmt(2 * R_LANDMARK * D_NEAR)
    v["SIGMA_LAND_FAR"] = fmt(2 * R_LANDMARK * D_FAR)
    v["NOISE_RATIO"] = fmt(R_MOVABLE / R_LANDMARK)
    v["N_MC"] = f"{N_MONTE_CARLO:,}"
    v["SIGMA_FAR_MEASURED"] = f"{res['sigma_far_measured']:.3f}"
    v["SERVER_VERSION"] = SERVER_VERSION
    v["RELEASE_DATE"] = RELEASE_DATE
    v["BACK_DASH_RATE"] = fmt(BACK_DASH_RATE)
    v["EFFORT_DEC"] = fmt(EFFORT_DEC)
    v["BALL_KEEP_PCT"] = fmt(BALL_DECAY * 100)
    v["TRY_W"] = str(TRY_MODE[0])
    v["TRY_K"] = str(TRY_MODE[1])
    v["N_TEAM"] = str(N_AGENTS // 2)
    return v


# =====================================================================
# ARTICLE TEMPLATE (raw string; placeholders @@...@@; no f-strings!)
# =====================================================================
TITLE = "Football in " + str(CYCLE_MS) + " Milliseconds"

TEMPLATE = r"""*Part 1: What the RoboCup 2D simulator is, and why every virtual player only sees part of the pitch*

> **About this series.** I am a high-school IB student. I build hardware projects, and I own a PYNQ-Z2 board. (That is an FPGA board: a board with a chip whose circuits you can reprogram.) In this series I explore the algorithms and math of football. I use the RoboCup Soccer Simulation 2D as my lab, and I ask how the ideas connect to real hardware.
>
> I used an AI assistant to help me draft the text and code. The ideas, the structure and the checking are mine.
>
> [[CHECKED: I checked these facts against the official manual: ... (author fills in)]]
>
> The Python demos are my own small toy models. They use equations from my sources, but they are not the official simulator. I did not run the official simulator (rcssserver) for this article.

[[AUTHOR: 2-3 real sentences about why I, a hardware student, care about this]]

## A strange way to play football

Imagine you play a match with your eyes almost closed. Up to @@CYCLES_PER_SEC@@ times every second, a voice whispers numbers to you: *"Ball: 23 metres, 15 degrees to your left. Teammate: 9 metres, straight ahead."*

Sometimes the numbers are a bit wrong. Sometimes nobody tells you about the player behind you. Then you have a short moment to decide: run, turn or kick.

Could you still play well?

This is close to the daily life of a player in the RoboCup 2D simulator. This part answers two questions:

- How can computer programs play football against each other?
- What does each player actually *know*?

The math is short: Pythagoras, angles, and a bell curve.

## The idea in plain words

RoboCup Soccer Simulation 2D is a football match inside a computer. It has two kinds of programs.

**The server.** A program called `rcssserver` runs the match. It moves the ball and the players and applies the rules. It also sends each player *limited* information about the world (Noda et al., 1998; RoboCup Soccer Simulator maintainers, n.d.).

**The clients.** Each player is a separate program, called a *client*. A client receives messages from the server and builds its own picture of the world. Then it decides what its own player should do next.

A full match has @@N_AGENTS@@ of these independent agents (Noda and Stone, 2003). An *agent* is a program that senses and acts on its own.

Clients talk with the server over UDP. UDP is a simple way to send short messages between programs on a network (Noda et al., 1998). Each client has its own limited point of view. Only the server sees the whole pitch.

Why football? The original authors chose it to test two hard things at the same time: **cooperation**, and **reacting in real time when you are not sure what is happening** (Noda et al., 1998).

> The server knows the truth. Each player only has a guess.

### Two worlds: hidden state and world model

This is the most important idea of the whole series.

1. **Hidden state** is the true position and speed of everything on the pitch. Only the server has it.
2. **World model** is each player's own *belief* about the hidden state. The player builds it from incomplete messages with small errors.

The simulator manual describes both sides: the physics inside the server, and the limited messages that each player receives (RoboCup Soccer Simulator maintainers, n.d.). Every later algorithm in this series works on the world model, not on the truth. That includes interception, positioning, passing and learning.

@@FIG_LOOP@@

## Five ways to look at the same thing

**The player on the pitch:** "I only see part of the pitch. Sometimes I am not sure who is behind me."

**The coach:** "I can't shout long instructions. A player can send a short message with the `say` command. It has at most @@SAY_CHARS@@ characters, from a limited set of letters and symbols. By default it reaches only @@SAY_RANGE_M@@ m. Each team can hear only a limited number of messages, and when too many arrive, they compete for those places." (RoboCup Soccer Simulator maintainers, n.d., §§4.3.1 and 4.5.5)

**The mathematician:** "Each player sees only part of the truth. In math words, this is a *partially observed* system. The true state is a long list of numbers. Each player sees only a small, noisy piece of that list."

**The programmer:** "Nobody starts from zero. HELIOS Base includes a client library called librcsc. It handles communication and timing, geometry, a world model and basic actions. It also includes a sample team, agent2d, which organizes decisions in agent, role and behavior layers." (Akiyama and Nakashima, 2014)

**The hardware engineer:** "This is a system with a clock and a deadline. New input arrives, and the answer must be ready before the next tick. A faster chip can only speed up the thinking step. Sending and receiving messages takes time too." A later part of this series looks at this in detail.

## How to read the formulas

Each formula has a short tag:

- **[Sim v19]** = *Simulator rule, v19.0.0.* A rule of the simulator, as described in the manual or the version @@SERVER_VERSION@@ code.
- **[Derived]** = *Derived here.* A result worked out in this article, with a proof.
- **[Toy]** = *Toy model.* My own simplification for teaching.

## The math, step by step

### Step 1: Time comes in ticks

The simulator does not run in smooth time. It runs in steps called **cycles**. One cycle is nominally @@CYCLE_MS@@ ms (RoboCup Soccer Simulator maintainers, n.d., §4.3). "Nominally" means this is the planned length.

@@EQ_CPS@@

**[Derived]** So a player can act up to @@CYCLES_PER_SEC@@ times per second. Think of a flip-book: each page is one cycle, and the world jumps from page to page.

Each cycle, a *body sensor* also tells the player about itself: its estimated speed, its effort, its stamina, and how many commands it has sent (§4.8). Stamina is like your energy level in a real match. It comes back in Part 2.

### Step 2: How wide, and how often, a player sees

A player sees inside a **view cone**, like the beam of a torch. Since version @@SYNC_DEFAULT_FROM@@, the default vision is called *synchronous*. The manual gives three widths (§4.3.2). **[Sim v19]**

- **narrow:** @@W_NARROW@@°, a new picture every @@K_NARROW@@ cycle
- **normal:** @@W_NORMAL@@°, a new picture every @@K_NORMAL@@ cycles
- **wide:** @@W_WIDE@@°, a new picture every @@K_WIDE@@ cycles

**Claim [Derived]:** On average, all three modes give the same view angle per cycle.

@@EQ_RATE@@

**Proof:**

1. Narrow: @@W_NARROW@@° per @@K_NARROW@@ cycle = @@RATE_ALL@@° per cycle.
2. Normal: @@W_NORMAL@@° per @@K_NORMAL@@ cycles = @@RATE_ALL@@° per cycle.
3. Wide: @@W_WIDE@@° per @@K_WIDE@@ cycles = @@RATE_ALL@@° per cycle. All three are equal. ∎

But be careful with this result. The three modes give the same angle per cycle only *on average*. A wide view shows more of the pitch at once, but each picture is older. A narrow view shows less of the pitch, but each picture is fresher. "Degrees per cycle" is a simple measure. It is not a full measure of information.

The gap between two pictures is @@GAP_NARROW_MS@@, @@GAP_NORMAL_MS@@ or @@GAP_WIDE_MS@@ ms. **[Derived]**

> The real choice: see more of the pitch at once, or see it more often.

One more detail. Objects very close to you but *outside* the cone can still be reported, but with limited identity (§4.3.2). It is like feeling someone right behind you without seeing their shirt number.

@@FIG_VIEW@@

In my toy timeline, the newest picture is at most @@AGE_NARROW_MS@@, @@AGE_NORMAL_MS@@ or @@AGE_WIDE_MS@@ ms old, for narrow, normal and wide. **[Toy]**

@@FIG_TIMELINE@@

### Step 3: Seeing in distance and direction

The server does not send "x = 12, y = 5". It sends **how far** and **in which direction**, measured from where you are looking.

Let @@M_R@@ be the position of an object *relative to you*. The manual gives these two rules (§4.3.2). **[Sim v19]**

@@EQ_DISTANCE@@

@@EQ_BEARING@@

In plain words:

- @@M_D@@ is the distance. It comes from Pythagoras.
- @@M_THETA@@ (the Greek letter theta) is the *bearing*: the direction of the object, compared with where you are looking.
- @@M_ATAN@@ is a calculator function. It gives the angle of the arrow (x, y) and picks the correct quarter of the circle.
- @@M_PHIB@@ is the direction your body faces. @@M_PHIH@@ is how far your head is turned, compared with your body. Their sum is where you are looking.
- The angle is "wrapped": it is kept between −180° and 180°.

Your world model must turn this back into a position.

**Claim [Derived]:**

@@EQ_INVERSE@@

**Proof:**

1. Add the body and head angles to both sides of the bearing rule. You get @@M_SUM_ANGLE@@, up to a full turn. A full turn does not change cos or sin.
2. atan2 gives the angle of the arrow r, measured from the x-axis.
3. Any arrow with length d and angle a has the parts @@M_COMPONENTS@@.
4. Put in our d and our angle, and you get the claim. ∎

My script tests this on @@N_RT@@ random examples. The largest error is about @@RT_ERR@@ m. That is only computer rounding.

There is one catch. To use these formulas, the player must also know its *own* position and body angle. Those are estimates too, so small errors can add up.

### Step 4: Seeing with noise

In science, **noise** means small random errors. The messages from the server have noise. Version @@SERVER_VERSION@@ has two noise models (RoboCup Soccer Simulator contributors, 2024).

**The default: rounded steps.** By default, distances are *quantized*. This means they are rounded to fixed steps, like a ruler that only shows whole centimetres. The rounding is done on the logarithm of the distance. My reading of the formula **[Derived]**: far objects get bigger rounding steps than close objects. My source does not give the step size, so I did not simulate this mode.

**The opt-in: Gaussian vision.** "Opt-in" means you must switch it on. Version @@SERVER_VERSION@@ has a setting called `gaussian_see`. With it, the seen distance comes from a random draw on a bell curve (a *normal* or *Gaussian* distribution). **[Sim v19]**

@@EQ_GAUSS@@

@@EQ_CLIP@@

Here:

- @@M_SIGMA@@ (sigma) measures how spread out the errors are.
- @@M_F@@ is the focus-to-object distance.
- @@M_RD@@ and @@M_RF@@ are two rates. In the default settings, both are @@R_MOV@@ for movable objects (the ball and players). For landmarks (fixed markers on the field) both are @@R_LAND@@.
- The max(0, Z) part makes sure the seen distance is never negative.

In my toy demo I assume that f equals d. **[Toy]** Then:

@@EQ_SIGMA_TOY@@

For example:

- at @@D_NEAR@@ m, σ = @@SIGMA_NEAR@@ m
- at @@D_FAR@@ m, σ = @@SIGMA_FAR@@ m

Far things are blurrier. For landmarks the rates are @@NOISE_RATIO@@ times smaller, so σ is only @@SIGMA_LAND_NEAR@@ m at @@D_NEAR@@ m and @@SIGMA_LAND_FAR@@ m at @@D_FAR@@ m.

My script draws @@N_MC@@ random samples at @@D_FAR@@ m. The measured spread is @@SIGMA_FAR_MEASURED@@ m. The formula says @@SIGMA_FAR@@ m.

One warning from my source: one line of the manual suggests multiplying the random sample by d. The version @@SERVER_VERSION@@ code does not do that, so my demo does not either.

@@FIG_NOISE@@

### A note on versions (said once in this series)

This series uses one exact version of the server: **rcssserver @@SERVER_VERSION@@**, released on @@RELEASE_DATE@@. The manual is official, but it is "living documentation". It is not frozen to one release, and it is not always consistent.

For some values, the manual's tables differ from the version @@SERVER_VERSION@@ code. Two examples: the code has `back_dash_rate = @@BACK_DASH_RATE@@` and `effort_dec = @@EFFORT_DEC@@`, and the manual's dash and stamina tables give different values. In this series I always use the version @@SERVER_VERSION@@ values.

## Putting it together: truth versus belief

Figure 5 shows the big idea in one picture. On the left is the hidden state: all @@N_AGENTS@@ players and the ball. On the right is what player 7 believes:

- solid dots for things it sees now (with small errors),
- hollow, faded dots for old memories,
- nothing at all for players it has lost track of.

@@FIG_BELIEF@@

The memories and drift on the right are my own toy, not rules of the simulator. But the shape of the problem is real: every decision is made on the right-hand picture.

## Common mistakes

- **"The client knows where everything is."** It doesn't. Only the server knows. Each client works with a partial belief that has errors.
- **"Wide view is always better."** Not always. A wide view shows more of the pitch at once, but the pictures are older. A narrow view shows less, but the pictures are fresher.
- **"Noise is the same everywhere."** In the Gaussian mode, the spread grows with distance.
- **"The client moves a robot."** A 2D client receives simulated observations and sends commands like `dash`, `turn` and `kick` (RoboCup Soccer Simulator maintainers, n.d.). There are no motors here.
- **"Every number in the manual is current."** Some tables disagree with the version @@SERVER_VERSION@@ code. Always say which version you use.

## What we learned

- The server holds the **hidden state**. Each of the @@N_AGENTS@@ clients builds its own **world model** from limited messages with errors.
- Time moves in **cycles** of nominally @@CYCLE_MS@@ ms. The view modes trade **width against freshness**, with the same @@M_DEG@@ per cycle on average.
- Players see **distance and bearing**, not x and y. With Gaussian vision, far objects are blurrier.

## Try it yourself

1. Run `build_part1.py`. Change `SEED` at the top and compare the new Figure 5.
2. Invent a new view mode: @@TRY_W@@° every @@TRY_K@@ cycles. How many degrees per cycle does it give? How old can the newest picture get? (The script prints the answer at the end.)
3. In the script, set `R_MOVABLE` to the landmark value (@@R_LAND@@). How much sharper does Figure 4 become?
4. Explain to a friend, in two sentences, why a footballer might *prefer* a narrow view.

[[AUTHOR: link to your GitHub repository with the code]]

## Next time

When you stop pedalling a bike, it slowly rolls to a stop. A kicked ball in the simulator does something similar. In the version @@SERVER_VERSION@@ code, when nothing else acts on it, the ball keeps @@BALL_KEEP_PCT@@% of its speed each cycle. In Part 2 the question is: **if I kick the ball at a certain speed, where will it stop?** The answer is a famous piece of school math: the geometric series.

## What I am not sure about

- My noise demo assumes that the focus distance f equals the distance d. My source defines f as the "focus-to-object distance" but does not explain when the two differ.
- My source does not give the step size of the default (rounded) noise, so I could not show how big the default errors are.
- I don't know exactly what "limited identity" looks like in a real message for close objects behind the player.

[[AUTHOR: add, remove or rewrite these doubts in your own words]]

## References

- Akiyama, H., and Nakashima, T. (2014). "HELIOS Base: An Open Source Package for the RoboCup Soccer 2D Simulation." In *RoboCup 2013: Robot World Cup XVII*, pp. 528–535. Springer. [add link after checking]
- Noda, I., Matsubara, H., Hiraki, K., and Frank, I. (1998). "Soccer Server: A Tool for Research on Multiagent Systems." *Applied Artificial Intelligence*, 12(2–3), 233–250. [add link after checking]
- Noda, I., and Stone, P. (2003). "The RoboCup Soccer Server and CMUnited Clients: Implemented Infrastructure for MAS Research." *Autonomous Agents and Multi-Agent Systems*, 7, 101–120. [add link after checking]
- RoboCup Soccer Simulator contributors. (2024). *rcssserver-19.0.0*. GitHub software release, published 25 March 2024. [add link after checking]
- RoboCup Soccer Simulator maintainers. (n.d., living documentation). "4. Soccer Server." In *The RoboCup Soccer Simulator Users Manual*. [add link after checking]
"""


# =====================================================================
# ARTICLE BUILDER
# =====================================================================
def figure_md(fig, target):
    """Image line + italic caption. dev.to gets absolute URLs only."""
    if target == "devto":
        url = BASE_URL + "/" + fig["file"]
    else:
        url = "figures/" + fig["file"]
    return "![" + fig["alt"] + "](" + url + ")\n*" + fig["caption"] + "*"


def header(target):
    if target == "devto":
        lines = [
            "---",
            'title: "' + TITLE + '"',
            "published: " + ("true" if PUBLISHED else "false"),
            'description: "' + DESCRIPTION + '"',
            "tags: " + ", ".join(TAGS),
            "series: " + SERIES,
            "# cover_image: " + BASE_URL + "/fig1_5_hidden_vs_belief.png",
            "---",
            "",
        ]
    else:
        lines = ["# " + TITLE, ""]
    return "\n".join(lines) + "\n"


def build_article(target, values, latex):
    text = TEMPLATE
    for key, val in values.items():
        text = text.replace("@@" + key + "@@", val)
    for key, lx in latex.items():
        if key.startswith("EQ_"):
            text = text.replace("@@" + key + "@@", math_block(lx, target))
        else:
            text = text.replace("@@" + key + "@@", math_inline(lx, target))
    for fig in FIGURES:
        text = text.replace("@@" + fig["key"] + "@@", figure_md(fig, target))
    leftover = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
    if leftover:
        raise RuntimeError("Unfilled placeholders in " + target + ": " + ", ".join(leftover))
    return header(target) + text


# =====================================================================
# MAIN
# =====================================================================
def main():
    set_style()

    print("Step 1/3: sanity checks")
    try:
        results = run_sanity_checks()
    except AssertionError as err:
        print("\nSANITY CHECK FAILED: " + str(err))
        print("Stopping. No figures and no article were written.")
        sys.exit(1)
    for line in CHECK_LOG:
        print("  OK  " + line)
    print(f"  {len(CHECK_LOG)} checks passed.")

    print("\nStep 2/3: figures")
    out = Path(OUT_DIR)
    fig_dir = out / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)
    for fig in FIGURES:
        fig["func"](fig_dir / fig["file"])
    n_before = len(CHECK_LOG)
    try:
        check_figure_files(fig_dir)
    except AssertionError as err:
        print("\nFIGURE CHECK FAILED: " + str(err))
        print("Stopping. No article was written.")
        sys.exit(1)
    print(f"  {len(CHECK_LOG) - n_before} figure checks passed.")

    print("\nStep 3/3: article")
    values = compute_numbers(results)
    latex = build_latex()
    written = {}
    for target, filename in TARGET_FILES.items():
        text = build_article(target, values, latex)
        path = out / filename
        path.write_text(text, encoding="utf-8")
        written[path] = text
        print(f"  wrote {path} ({len(text.split()):,} words incl. markup)")

    # Exercise answer
    tw, tk = TRY_MODE
    print(f"\nAnswer to 'Try it yourself' 2: {tw}° / {tk} cycles = {fmt(tw / tk)}° per cycle; "
          f"newest picture at most {(tk - 1) * CYCLE_MS} ms old (toy timing).")

    # Placeholder warning
    print()
    any_left = False
    for path, text in written.items():
        found = re.findall(r"\[\[(.+?)\]\]", text, flags=re.DOTALL)
        if found:
            any_left = True
            print(f"WARNING: {len(found)} author placeholder(s) still in {path}:")
            for item in found:
                print("   - [[" + item[:90] + ("..." if len(item) > 90 else "") + "]]")
    if any_left:
        print("Fill these in before you publish.")
    else:
        print("No [[...]] placeholders left.")
    if "USERNAME/REPO" in BASE_URL:
        print("WARNING: BASE_URL still contains USERNAME/REPO. Edit the CONFIG block.")


if __name__ == "__main__":
    main()
