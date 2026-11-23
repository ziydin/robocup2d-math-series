#!/usr/bin/env python3
"""
build_part2.py

One self-contained build script for Part 2 of the series
"Football Math with RoboCup 2D": "Why the Ball Stops: Decay and the Geometric Series".

What it does, in this order:
  1. Runs sanity checks. If one fails, it stops and writes nothing.
  2. Draws every figure as PNG (1600 px wide) into OUT_DIR/figures/.
  3. Computes every number that appears in the article text.
  4. Writes the article twice:
       OUT_DIR/part2_devto.md   (dev.to, KaTeX liquid tags, absolute image URLs)
       OUT_DIR/part2_github.md  (GitHub, $...$ math, relative image paths)
     Before writing, it checks that no empty slots ([[...]], TODO, ...) are left.

All demos are TOY models that use equations described in the source report.
This script does NOT run rcssserver.

Needs: Python 3.10+, numpy, matplotlib.
"""

import math
import re
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")  # draw straight to files, no window needed
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle

# =====================================================================
# CONFIG (edit these)
# =====================================================================
TARGET_FILES = {"devto": "part2_devto.md", "github": "part2_github.md"}
BASE_URL = "https://raw.githubusercontent.com/ziydin/robocup2d-math-series/main/part2/figures"
REPO_URL = "https://github.com/ziydin/robocup2d-math-series"
SERVER_REPO_URL = "https://github.com/rcsoccersim/rcssserver"
MANUAL_URL = "https://rcsoccersim.github.io/manual/"
OUT_DIR = "part2"
SERIES = "Football Math with RoboCup 2D"
TAGS = ["robotics", "python", "math", "beginners"]
SEED = 7
PUBLISHED = False

# Add a short string here ONLY after you really checked it in the manual or code,
# for example: "ball decay 0.94 (server.conf)".
VERIFIED_ITEMS = []

TITLE = "Why the Ball Stops: Decay and the Geometric Series"
DESCRIPTION = ("How a kicked ball in the RoboCup 2D simulator slows down, and how a "
               "geometric series tells us where it stops.")

# =====================================================================
# VALUES FROM THE SOURCE REPORT (rcssserver v19.0.0, as stated there)
# Check each one before publishing.
# =====================================================================
SERVER_VERSION = "19.0.0"
RELEASE_DATE = "25 March 2024"
CYCLE_MS = 100                 # nominal cycle length (from Part 1)
BALL_DECAY = 0.94
PLAYER_DECAY = 0.40
BALL_SPEED_MAX = 3.0
PLAYER_SPEED_MAX = 1.05
BALL_ACCEL_MAX = 2.7
PLAYER_ACCEL_MAX = 1.0
BALL_RAND = 0.05               # velocity noise rate, ball
PLAYER_RAND = 0.10             # velocity noise rate, player
KICK_RATE = 0.027              # k_kick
KICK_MARGIN = 0.7              # m (metres)
KICK_ANGLE_W = 0.25            # weight of alpha/pi in the readable kick formula
KICK_GAP_W = 0.25              # weight of g/m in the readable kick formula
BACK_DASH_RATE = 0.7           # v19 code value (manual table differs)
EFFORT_DEC = 0.005             # v19 code value (manual table differs)

# =====================================================================
# TOY CHOICES (NOT from the report; never quote them as facts)
# =====================================================================
SLOW_SPEED = 0.1               # what I call "slow", m per cycle
KICK_POWER_TOY = 100.0         # toy maximum kick power (not in the report)
D_EXAMPLE = 20.0               # example target distance, m
N_ARRIVE = 10                  # example arrival time, cycles
N_IMPOSSIBLE = 5               # example of an impossible arrival time
N_ROLL = 300                   # cycles to simulate a roll
N_MC = 4000                    # noisy kicks in the Monte Carlo test
PICTURE_DECAY = 0.6            # only for the multiply-and-subtract picture
PICTURE_TERMS = 6              # only for the multiply-and-subtract picture
FX_BITS = 16                   # fixed-point word size
FX_FRAC_D = 15                 # fraction bits for the decay factor (Q1.15)
FX_FRAC_V = 12                 # fraction bits for the velocity
ACC_BITS = 32                  # position register size
FX_LONG_1, FX_LONG_2 = 1000, 2000
# "Try it yourself" inputs
T1_DIST = 30.0
T2_SPEED = 2.0
T3_DECAY = 0.95
T4_DECAY = 0.6

# =====================================================================
# STYLE (Okabe-Ito colorblind-safe palette)
# =====================================================================
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
VERMILLION = "#D55E00"
SKY = "#56B4E9"
GREY = "#8C8C8C"
LIGHT = "#D9D9D9"
BLACK = "#000000"

DPI = 200
FIG_WIDTH_IN = 8.0             # 8 in x 200 dpi = 1600 px
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


# =====================================================================
# MATH AND TOY PHYSICS
# =====================================================================
def closed_speed(v0, d, n):
    """[Derived] speed after n cycles: v0 * d^n."""
    return v0 * d ** n


def closed_distance(v0, d, n):
    """[Derived] distance after n cycles: v0 * (1 - d^n) / (1 - d)."""
    return v0 * (1 - d ** n) / (1 - d)


def stop_distance(v0, d):
    """[Derived] ceiling: v0 / (1 - d)."""
    return v0 / (1 - d)


def geo_sum_loop(a, d, n):
    """Add a + a d + ... + a d^(n-1) one term at a time."""
    total, term = 0.0, a
    for _ in range(n):
        total += term
        term *= d
    return total


def cycles_until_slow(v0, d, s):
    """[Derived] smallest n with v0 * d^n < s."""
    return math.floor(math.log(s / v0) / math.log(d)) + 1


def half_life(d):
    """[Derived] cycles to lose half the speed."""
    return math.log(2) / -math.log(d)


def kick_speed_to_stop_at(dist, d):
    """[Derived] v0 = D (1 - d)."""
    return dist * (1 - d)


def kick_speed_to_arrive(dist, d, n):
    """[Derived] v0 = D (1 - d) / (1 - d^n)."""
    return dist * (1 - d) / (1 - d ** n)


def min_cycles_to_reach(dist, d, vmax):
    """[Derived] smallest n with vmax (1 - d^n)/(1 - d) >= D, or None."""
    x = 1 - dist * (1 - d) / vmax
    if x <= 0:
        return None
    return math.ceil(math.log(x) / math.log(d))


def roll_ball_loop(v0, d, n_cycles, vmax):
    """[Toy] step by step: move first, then decay. Returns positions and speeds."""
    pos, v = 0.0, min(v0, vmax)
    positions, speeds = [pos], [v]
    for _ in range(n_cycles):
        pos += v          # 1. move
        v *= d            # 2. slow down
        positions.append(pos)
        speeds.append(v)
    return np.array(positions), np.array(speeds)


def player_run_loop(n_dash, n_coast, accel, d, vmax):
    """[Toy] full push while dashing, then coast. Returns moving speeds and positions."""
    v, pos = 0.0, 0.0
    moving, positions = [], [0.0]
    for i in range(n_dash + n_coast):
        a = accel if i < n_dash else 0.0
        u = min(v + a, vmax)   # push, then speed cap
        pos += u               # move
        v = d * u              # decay
        moving.append(u)
        positions.append(pos)
    return np.array(moving), np.array(positions)


def roll_ball_noisy(v0, d, vmax, r, n_cycles, n_runs, rng):
    """[Toy + Sim v19 noise shape] many noisy rolls at once, kicked along x."""
    pos = np.zeros((n_runs, 2))
    vel = np.zeros((n_runs, 2))
    vel[:, 0] = v0
    for _ in range(n_cycles):
        u = vel.copy()                                   # no push after the kick
        speed = np.hypot(u[:, 0], u[:, 1])
        fast = speed > vmax
        u[fast] *= (vmax / speed[fast])[:, None]         # cap before noise
        speed = np.hypot(u[:, 0], u[:, 1])
        radius = rng.uniform(0.0, r * speed)             # uniform RADIUS
        angle = rng.uniform(-np.pi, np.pi, n_runs)       # uniform direction
        u += np.column_stack([radius * np.cos(angle), radius * np.sin(angle)])
        pos += u
        vel = d * u
    return pos


def spread_prediction(v0, d, r):
    """[Derived, approximate] sigma_stop = r v0 / ((1-d) sqrt(6 (1-d^2)))."""
    return r * v0 / ((1 - d) * math.sqrt(6 * (1 - d ** 2)))


def kick_factor(alpha, gap):
    """Readable part of the kick formula (from my source, check it)."""
    return 1 - KICK_ANGLE_W * alpha / np.pi - KICK_GAP_W * gap / KICK_MARGIN


def to_fixed(x, frac_bits):
    """Real number -> integer with frac_bits fraction bits (round to nearest)."""
    return int(round(x * (1 << frac_bits)))


def roll_fixed(v0, d, frac_v, frac_d, mode, n_cycles):
    """[Toy] integer-only roll. mode 'round' or 'floor' after each multiply."""
    dq = to_fixed(d, frac_d)
    v = to_fixed(v0, frac_v)
    pos = 0
    half = 1 << (frac_d - 1)
    stop_cycle = None
    for n in range(1, n_cycles + 1):
        pos += v
        if mode == "round":
            v = (v * dq + half) >> frac_d
        else:
            v = (v * dq) >> frac_d
        if v == 0 and stop_cycle is None:
            stop_cycle = n
    return pos / (1 << frac_v), v, stop_cycle, pos


# =====================================================================
# NUMBER FORMATTING
# =====================================================================
SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def g3(x):
    """Short format: 0.94, 50, 0.027."""
    return f"{x:.3g}"


def sci_text(x, sig=2):
    """2.4e-06 -> '2.4 × 10⁻⁶' (readable in Markdown)."""
    if x == 0:
        return "0"
    mant, exp = f"{x:.{sig - 1}e}".split("e")
    return mant + " × 10" + str(int(exp)).translate(SUP)


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
    res = {}
    d, pd = BALL_DECAY, PLAYER_DECAY

    # --- config ---
    check(0 < len(TAGS) <= 4, "dev.to: between 1 and 4 tags")
    check(all(re.fullmatch(r"[a-z0-9]+", t) for t in TAGS),
          "dev.to: tags use only lowercase letters and digits")
    check(BASE_URL.startswith("https://") and not BASE_URL.endswith("/"),
          "BASE_URL is https and has no trailing slash")
    check(set(TARGET_FILES) <= {"devto", "github"} and TARGET_FILES,
          "TARGET_FILES only contains 'devto' and/or 'github'")

    # --- 1. geometric sum: loop vs closed form ---
    worst, tests = 0.0, 0
    for dd in (0.94, 0.4, 0.6, 0.95, 0.5):
        for n in (1, 2, 5, 10, 55, 200):
            for a in (1.0, 2.7):
                worst = max(worst, abs(geo_sum_loop(a, dd, n) - closed_distance(a, dd, n)))
                tests += 1
    pos, spd = roll_ball_loop(BALL_SPEED_MAX, d, N_ROLL, BALL_SPEED_MAX)
    n_arr = np.arange(N_ROLL + 1)
    err_p = float(np.max(np.abs(pos - closed_distance(BALL_SPEED_MAX, d, n_arr))))
    err_v = float(np.max(np.abs(spd - closed_speed(BALL_SPEED_MAX, d, n_arr))))
    tests += 2 * (N_ROLL + 1)
    res["cf_err"] = max(worst, err_p, err_v)
    res["cf_tests"] = tests
    check(res["cf_err"] < 1e-9, f"closed forms match the loop ({tests} comparisons, "
                                f"largest gap {res['cf_err']:.1e})")

    # --- 2. ceiling ---
    res["ceiling"] = stop_distance(BALL_SPEED_MAX, d)
    res["ceil_rest"] = stop_distance(BALL_ACCEL_MAX, d)
    long_pos, _ = roll_ball_loop(BALL_SPEED_MAX, d, 2000, BALL_SPEED_MAX)
    check(abs(long_pos[-1] - res["ceiling"]) < 1e-9, "a long roll ends at v0/(1-d)")
    check(bool(np.all(np.diff(long_pos) >= 0)) and long_pos[-1] <= res["ceiling"] + 1e-9,
          "distance only grows and never passes the ceiling")
    check(BALL_ACCEL_MAX < BALL_SPEED_MAX, "a kick from rest is below the speed cap")

    # --- 3. remaining distance = v_n / (1 - d) ---
    rem = res["ceiling"] - pos[:100]
    check(float(np.max(np.abs(rem - spd[:100] / (1 - d)))) < 1e-9,
          "remaining distance equals current speed / (1 - d)")

    # --- 4. slow, half-life ---
    n_slow = cycles_until_slow(BALL_SPEED_MAX, d, SLOW_SPEED)
    n_slow_loop = int(np.argmax(spd < SLOW_SPEED))
    check(n_slow == n_slow_loop, f"speed below {SLOW_SPEED} first at cycle {n_slow} (formula = loop)")
    res["n_slow"] = n_slow
    res["n_slow_exact"] = math.log(SLOW_SPEED / BALL_SPEED_MAX) / math.log(d)
    res["dist_slow"] = float(pos[n_slow])
    res["half"] = half_life(d)
    res["p_half"] = half_life(pd)
    check(abs(d ** res["half"] - 0.5) < 1e-12, "half-life: d^h = 1/2")
    res["half_frac"] = 1 - d ** res["half"]
    res["two_half_frac"] = 1 - d ** (2 * res["half"])
    check(abs(res["half_frac"] - 0.5) < 1e-12 and abs(res["two_half_frac"] - 0.75) < 1e-12,
          "after 1 and 2 half-lives: 50% and 75% of the distance")

    # --- 5. inverse problems ---
    v_stop = kick_speed_to_stop_at(D_EXAMPLE, d)
    p_, _ = roll_ball_loop(v_stop, d, 2000, BALL_SPEED_MAX)
    check(abs(p_[-1] - D_EXAMPLE) < 1e-9, f"kick {v_stop:.2f} stops at {D_EXAMPLE:g} m")
    check(v_stop <= BALL_ACCEL_MAX, "that kick is possible from rest")
    res["v_stop"] = v_stop
    v_arr = kick_speed_to_arrive(D_EXAMPLE, d, N_ARRIVE)
    p_, s_ = roll_ball_loop(v_arr, d, N_ARRIVE, BALL_SPEED_MAX)
    check(abs(p_[N_ARRIVE] - D_EXAMPLE) < 1e-9, f"kick {v_arr:.2f} arrives in {N_ARRIVE} cycles")
    check(v_arr <= BALL_ACCEL_MAX, "arrival kick is possible from rest")
    res["v_arr"], res["v_arr_end"] = v_arr, float(s_[N_ARRIVE])
    n_min = min_cycles_to_reach(D_EXAMPLE, d, BALL_ACCEL_MAX)
    n_min_loop = next(n for n in range(1, 1000)
                      if closed_distance(BALL_ACCEL_MAX, d, n) >= D_EXAMPLE)
    check(n_min == n_min_loop, f"fastest arrival {n_min} cycles (formula = search)")
    res["n_min"] = n_min
    res["n_min_exact"] = (math.log(1 - D_EXAMPLE * (1 - d) / BALL_ACCEL_MAX) / math.log(d))
    res["v_nmin_m1"] = kick_speed_to_arrive(D_EXAMPLE, d, n_min - 1)
    check(res["v_nmin_m1"] > BALL_ACCEL_MAX, "one cycle faster needs too big a kick")
    res["v_imp"] = kick_speed_to_arrive(D_EXAMPLE, d, N_IMPOSSIBLE)
    res["reach_imp"] = closed_distance(BALL_ACCEL_MAX, d, N_IMPOSSIBLE)
    check(res["v_imp"] > BALL_ACCEL_MAX and res["reach_imp"] < D_EXAMPLE,
          f"{N_IMPOSSIBLE} cycles is impossible")

    # --- 6. player ---
    n_dash, n_coast = 10, 60
    moving, ppos = player_run_loop(n_dash, n_coast, PLAYER_ACCEL_MAX, pd, PLAYER_SPEED_MAX)
    res["p_v1"] = float(moving[0])
    res["p_cap_cycle"] = next(i for i, u in enumerate(moving)
                              if abs(u - PLAYER_SPEED_MAX) < 1e-12) + 1
    m_free, _ = player_run_loop(300, 0, PLAYER_ACCEL_MAX, pd, float("inf"))
    res["p_uncap"] = PLAYER_ACCEL_MAX / (1 - pd)
    check(abs(m_free[-1] - res["p_uncap"]) < 1e-9, "uncapped steady speed = a/(1 - d_p)")
    check(res["p_uncap"] > PLAYER_SPEED_MAX, "the speed cap really limits the player")
    res["p_v_after"] = float(moving[n_dash])
    check(abs(res["p_v_after"] - pd * PLAYER_SPEED_MAX) < 1e-12, "first coast move = d_p * cap")
    res["p_coast"] = float(ppos[-1] - ppos[n_dash])
    check(abs(res["p_coast"] - pd * PLAYER_SPEED_MAX / (1 - pd)) < 1e-9,
          "player coast distance = d_p v_max / (1 - d_p)")
    res["b_coast"] = d * PLAYER_SPEED_MAX / (1 - d)
    bp, _ = roll_ball_loop(d * PLAYER_SPEED_MAX, d, 2000, BALL_SPEED_MAX)
    check(abs(bp[-1] - res["b_coast"]) < 1e-9, "ball coast at the same speed (loop = formula)")

    # --- 7. one noise push ---
    m = 200_000
    radius = rng.uniform(0, BALL_RAND, m)
    ang = rng.uniform(-np.pi, np.pi, m)
    push = np.column_stack([radius * np.cos(ang), radius * np.sin(ang)])
    se = BALL_RAND / math.sqrt(6) / math.sqrt(m)
    check(bool(np.all(np.abs(push.mean(axis=0)) < 5 * se)), "average noise push is zero")
    check(float(radius.max()) <= BALL_RAND, "noise radius never above r * speed")
    check(abs(np.mean(radius ** 2) / (BALL_RAND ** 2 / 3) - 1) < 0.02,
          "average squared push = (r * speed)^2 / 3")

    # --- 8. Monte Carlo stopping points ---
    stops = roll_ball_noisy(BALL_ACCEL_MAX, d, BALL_SPEED_MAX, BALL_RAND, N_ROLL, N_MC, rng)
    res["stops"] = stops
    res["stop_det"] = closed_distance(BALL_ACCEL_MAX, d, N_ROLL)
    res["spread_pred"] = spread_prediction(BALL_ACCEL_MAX, d, BALL_RAND)
    res["mean_x"], res["mean_y"] = float(stops[:, 0].mean()), float(stops[:, 1].mean())
    res["spread_x"], res["spread_y"] = float(stops[:, 0].std()), float(stops[:, 1].std())
    se = res["spread_pred"] / math.sqrt(N_MC)
    check(abs(res["mean_x"] - res["stop_det"]) < 5 * se and abs(res["mean_y"]) < 5 * se,
          "noise keeps the average stop (Monte Carlo)")
    for key in ("spread_x", "spread_y"):
        check(abs(res[key] / res["spread_pred"] - 1) < 0.05,
              f"{key}: within 5% of the spread formula")

    # --- 9. kick (readable magnitude only) ---
    check(abs(kick_factor(0.0, 0.0) - 1.0) < 1e-12, "kick factor 1 for ball ahead and touching")
    res["factor_min"] = float(kick_factor(np.pi, KICK_MARGIN))
    check(abs(res["factor_min"] - 0.5) < 1e-12, "kick factor 0.5 for ball behind and far")
    res["kick_max"] = KICK_POWER_TOY * KICK_RATE
    res["kick_min"] = res["kick_max"] * res["factor_min"]
    check(abs(res["kick_max"] - BALL_ACCEL_MAX) < 1e-9, "toy P_max * k_kick = ball accel cap")

    # --- 10. fixed point ---
    dq = to_fixed(d, FX_FRAC_D)
    res["dq"], res["dq_val"] = dq, dq / (1 << FX_FRAC_D)
    res["dq_err"] = abs(res["dq_val"] - d)
    check(dq < (1 << (FX_BITS - 1)), f"decay fits in signed {FX_BITS}-bit")
    check(res["dq_err"] <= 2 ** -(FX_FRAC_D + 1), "decay error is at most half a step")
    res["ceil_q"] = BALL_SPEED_MAX / (1 - res["dq_val"])
    v0_int = to_fixed(BALL_ACCEL_MAX, FX_FRAC_V)
    check(v0_int < (1 << (FX_BITS - 1)), f"velocity fits in signed {FX_BITS}-bit")
    fd, fv, fstop, fpos = roll_fixed(BALL_ACCEL_MAX, d, FX_FRAC_V, FX_FRAC_D, "floor", FX_LONG_1)
    res["float_dist"] = stop_distance(BALL_ACCEL_MAX, d)
    check(fstop is not None and fv == 0, "round-down ball stops")
    check(fd < res["float_dist"], "round-down ball stops short")
    check(fpos >= (1 << (FX_BITS - 1)) and fpos < (1 << (ACC_BITS - 1)),
          f"position needs more than {FX_BITS} bits but fits in {ACC_BITS}")
    res["floor_dist"], res["floor_cycles"] = fd, fstop
    r1, v1, s1, _ = roll_fixed(BALL_ACCEL_MAX, d, FX_FRAC_V, FX_FRAC_D, "round", FX_LONG_1)
    r2, v2, s2, _ = roll_fixed(BALL_ACCEL_MAX, d, FX_FRAC_V, FX_FRAC_D, "round", FX_LONG_2)
    check(v1 > 0 and v1 == v2 and s1 is None, "round-to-nearest ball gets stuck and never stops")
    creep = v1 / (1 << FX_FRAC_V)
    check(abs((r2 - r1) - creep * (FX_LONG_2 - FX_LONG_1)) < 1e-9, "stuck ball creeps at a constant speed")
    res["round_stuck"], res["round_creep"] = v1, creep
    res["round_d1"], res["round_d2"] = r1, r2

    # --- 11. try-it-yourself answers ---
    res["t1"] = kick_speed_to_stop_at(T1_DIST, d)
    p_, _ = roll_ball_loop(res["t1"], d, 2000, BALL_SPEED_MAX)
    check(abs(p_[-1] - T1_DIST) < 1e-9, "task 1 answer checked by loop")
    res["t2"] = cycles_until_slow(T2_SPEED, d, SLOW_SPEED)
    _, s_ = roll_ball_loop(T2_SPEED, d, N_ROLL, BALL_SPEED_MAX)
    check(res["t2"] == int(np.argmax(s_ < SLOW_SPEED)), "task 2 answer checked by loop")
    res["t3"] = stop_distance(BALL_SPEED_MAX, T3_DECAY)
    p_, _ = roll_ball_loop(BALL_SPEED_MAX, T3_DECAY, 3000, BALL_SPEED_MAX)
    check(abs(p_[-1] - res["t3"]) < 1e-9, "task 3 answer checked by loop")
    mv, pp = player_run_loop(10, 200, PLAYER_ACCEL_MAX, T4_DECAY, PLAYER_SPEED_MAX)
    res["t4"] = float(pp[-1] - pp[10])
    check(abs(res["t4"] - T4_DECAY * PLAYER_SPEED_MAX / (1 - T4_DECAY)) < 1e-9,
          "task 4 answer checked by loop")
    return res


# continues build_part2.py after run_sanity_checks
# =====================================================================
# NUMBERS FOR THE TEXT (every number in the article comes from here)
# =====================================================================
# Keys that Message B must provide:
#   build_latex(): EQ_UPDATE, EQ_SPEED, EQ_SUM_S, EQ_SUM_DS, EQ_SUM_SUB, EQ_DIST,
#                  EQ_CEIL, EQ_REMAIN, EQ_SLOW, EQ_HALF, EQ_INV_STOP, EQ_INV_ARR,
#                  EQ_NMIN, EQ_PLAYER, EQ_NOISE, EQ_SPREAD, EQ_KICK, EQ_FIXED
#   FIGURES:       FIG_SPEED, FIG_DIST, FIG_GEO, FIG_CLOUD, FIG_KICK
def verified_sentence():
    if VERIFIED_ITEMS:
        return ("I checked these against the official manual or the rcssserver code: "
                + "; ".join(VERIFIED_ITEMS) + ".")
    return ("The numbers in this article come from a literature report about the manual "
            "and the rcssserver " + SERVER_VERSION + " code. I have not yet compared each "
            "one with the original source.")


def compute_numbers(r):
    d, pd = BALL_DECAY, PLAYER_DECAY
    v0_int = to_fixed(BALL_ACCEL_MAX, FX_FRAC_V)
    v = {
        # links and boxes
        "SERIES": SERIES, "REPO_URL": REPO_URL, "SERVER_REPO_URL": SERVER_REPO_URL,
        "MANUAL_URL": MANUAL_URL, "VERIFIED_SENTENCE": verified_sentence(),
        "SERVER_VERSION": SERVER_VERSION, "RELEASE_DATE": RELEASE_DATE,
        "BACK_DASH_RATE": g3(BACK_DASH_RATE), "EFFORT_DEC": g3(EFFORT_DEC),
        # time and basic values
        "CYCLE_MS": str(CYCLE_MS), "CYCLES_PER_SEC": g3(1000 / CYCLE_MS),
        "BALL_DECAY": g3(d), "PLAYER_DECAY": g3(pd),
        "BALL_KEEP_PCT": g3(d * 100), "BALL_LOSS_PCT": g3((1 - d) * 100),
        "BALL_LOSS_FRAC": g3(1 - d),
        "PLAYER_KEEP_PCT": g3(pd * 100), "PLAYER_LOSS_PCT": g3((1 - pd) * 100),
        "P_D2": g3(pd ** 2),
        "BALL_VMAX": f"{BALL_SPEED_MAX:.1f}", "BALL_AMAX": f"{BALL_ACCEL_MAX:.1f}",
        "PLAYER_VMAX": g3(PLAYER_SPEED_MAX), "PLAYER_AMAX": f"{PLAYER_ACCEL_MAX:.1f}",
        "BALL_RAND": g3(BALL_RAND), "PLAYER_RAND": g3(PLAYER_RAND),
        "SPEED_MPS": g3(BALL_SPEED_MAX * 1000 / CYCLE_MS),
        # closed form and ceiling
        "CF_TESTS": f"{r['cf_tests']:,}", "CF_ERR": sci_text(r["cf_err"]),
        "CEILING": g3(r["ceiling"]), "CEIL_REST": g3(r["ceil_rest"]),
        "REMAIN_FACTOR": g3(1 / (1 - d)),
        # slow and half-life
        "SLOW": g3(SLOW_SPEED), "N_SLOW": str(r["n_slow"]),
        "N_SLOW_EXACT": f"{r['n_slow_exact']:.2f}",
        "T_SLOW": g3(r["n_slow"] * CYCLE_MS / 1000),
        "DIST_SLOW": f"{r['dist_slow']:.1f}",
        "PCT_SLOW": f"{100 * r['dist_slow'] / r['ceiling']:.1f}",
        "HALF": f"{r['half']:.1f}", "T_HALF": g3(r["half"] * CYCLE_MS / 1000),
        "HALF_PCT": g3(100 * r["half_frac"]), "TWO_HALF_PCT": g3(100 * r["two_half_frac"]),
        "P_HALF": f"{r['p_half']:.2f}",
        # inverse problems
        "D_EXAMPLE": g3(D_EXAMPLE), "V_STOP": g3(r["v_stop"]),
        "N_ARRIVE": str(N_ARRIVE), "V_ARR": f"{r['v_arr']:.2f}",
        "V_ARR_END": f"{r['v_arr_end']:.2f}",
        "N_MIN": str(r["n_min"]), "N_MIN_EXACT": f"{r['n_min_exact']:.2f}",
        "N_MIN_M1": str(r["n_min"] - 1), "V_NMIN_M1": f"{r['v_nmin_m1']:.2f}",
        "N_IMP": str(N_IMPOSSIBLE), "V_IMP": f"{r['v_imp']:.2f}",
        "REACH_IMP": f"{r['reach_imp']:.1f}",
        # player
        "P_V1": g3(r["p_v1"]), "P_CAP_CYCLE": str(r["p_cap_cycle"]),
        "P_UNCAP": f"{r['p_uncap']:.2f}", "P_SUM": f"{1 / (1 - pd):.2f}",
        "P_V_AFTER": g3(r["p_v_after"]), "P_COAST": g3(r["p_coast"]),
        "B_COAST": f"{r['b_coast']:.1f}",
        "COAST_RATIO": f"{r['b_coast'] / r['p_coast']:.0f}",
        # noise
        "N_MC": f"{N_MC:,}", "N_ROLL": str(N_ROLL),
        "NOISE_SPEED_PCT": g3(100 * BALL_RAND),
        "STOP_DET": f"{r['stop_det']:.2f}",
        "MEAN_X": f"{r['mean_x']:.2f}", "MEAN_Y": f"{r['mean_y']:.2f}",
        "SPREAD_X": f"{r['spread_x']:.2f}", "SPREAD_Y": f"{r['spread_y']:.2f}",
        "SPREAD_PRED": f"{r['spread_pred']:.2f}",
        # kick
        "KICK_RATE": g3(KICK_RATE), "KICK_MARGIN": g3(KICK_MARGIN),
        "KICK_ANGLE_W": g3(KICK_ANGLE_W), "KICK_GAP_W": g3(KICK_GAP_W),
        "KICK_POWER_TOY": g3(KICK_POWER_TOY),
        "KICK_MAX": g3(r["kick_max"]), "KICK_MIN": g3(r["kick_min"]),
        "FACTOR_MIN_PCT": g3(100 * r["factor_min"]),
        # fixed point
        "FX_BITS": str(FX_BITS), "FX_FRAC_D": str(FX_FRAC_D),
        "FX_INT_D": str(FX_BITS - FX_FRAC_D), "FX_FRAC_V": str(FX_FRAC_V),
        "FX_SCALE_D": f"{1 << FX_FRAC_D:,}",
        "FX_STEP_V_MM": f"{1000 / (1 << FX_FRAC_V):.3f}",
        "ACC_BITS": str(ACC_BITS),
        "DQ": str(r["dq"]), "DQ_VAL": f"{r['dq_val']:.9f}", "DQ_ERR": sci_text(r["dq_err"]),
        "CEIL_Q": f"{r['ceil_q']:.4f}",
        "CEIL_SHIFT_MM": f"{(r['ceil_q'] - r['ceiling']) * 1000:.1f}",
        "V0_INT": f"{v0_int:,}",
        "FLOAT_DIST": g3(r["float_dist"]),
        "FLOOR_DIST": f"{r['floor_dist']:.3f}", "FLOOR_CYCLES": str(r["floor_cycles"]),
        "FLOOR_SHORT_CM": f"{(r['float_dist'] - r['floor_dist']) * 100:.1f}",
        "ROUND_STUCK": str(r["round_stuck"]),
        "ROUND_CREEP_MM": f"{r['round_creep'] * 1000:.2f}",
        "FX_LONG_1": f"{FX_LONG_1:,}", "FX_LONG_2": f"{FX_LONG_2:,}",
        "ROUND_D1": f"{r['round_d1']:.2f}", "ROUND_D2": f"{r['round_d2']:.2f}",
        # try it yourself (answers are printed by main)
        "T1_DIST": g3(T1_DIST), "T2_SPEED": g3(T2_SPEED),
        "T3_DECAY": g3(T3_DECAY), "T4_DECAY": g3(T4_DECAY),
    }
    return v


# =====================================================================
# ARTICLE TEMPLATE (raw string; placeholders @@...@@; no f-strings!)
# =====================================================================
TEMPLATE = r"""*Part 2 of @@SERIES@@: a rolling ball, a famous school formula, and why it matters for chips*

> **About this part.** I am a high-school IB student, and I build hardware projects on my PYNQ-Z2 FPGA board. I used an AI assistant to help me draft the text and code. The ideas, the structure and the final decisions are mine.
>
> @@VERIFIED_SENTENCE@@
>
> For this article I ran the build script and read the literature report. The Python demos are my own toy models. I did not run the official simulator (rcssserver). All code is here: @@REPO_URL@@

I love football, and I am trying to understand its theory and its basic logic. That is why I wanted to look deeply at the math of the game. I am also interested in hardware engineering. I want to build a bridge between the two fields, so that I can see the whole picture.

## The bike that does not stop at once

Stop pedalling on a flat road. Your bike does not stop at once. It rolls on and slows down little by little.

A kicked ball in the RoboCup 2D simulator does the same. Each cycle it keeps @@BALL_KEEP_PCT@@% of its speed and loses @@BALL_LOSS_PCT@@%. (A cycle is one step of the simulation, nominally @@CYCLE_MS@@ ms. See Part 1.)

So here is today's question: **if I kick the ball, where will it stop?**

My first guess was "it rolls forever", because it never loses *all* its speed. That guess is wrong, and the reason is one of the nicest ideas in school math: the **geometric series**.

*Version note: all values are for rcssserver @@SERVER_VERSION@@ (@@RELEASE_DATE@@). Some manual tables differ from this code, for example `back_dash_rate = @@BACK_DASH_RATE@@` and `effort_dec = @@EFFORT_DEC@@` in the code (details in Part 1).*

## The idea in plain words

The word **decay** here means "slowing down by the same fraction every cycle". The ball's decay is @@BALL_DECAY@@. The player's decay is @@PLAYER_DECAY@@.

Distances are in simulator units, which I call metres. Speeds are in metres per cycle. The ball's speed cap is @@BALL_VMAX@@ per cycle. At @@CYCLES_PER_SEC@@ cycles per second that is @@SPEED_MPS@@ m/s.

**My update rule [Toy].** For a rolling ball that nobody touches, I use this order in each cycle:

1. move: position = position + velocity,
2. slow down: velocity = decay × velocity.

My source describes the same order, but I have not checked it in the code. So I mark it as my assumption.

@@EQ_UPDATE@@

## The math, step by step

### Step 1: the speed

Each cycle multiplies the speed by d. After n cycles we multiplied n times. **[Derived]**

@@EQ_SPEED@@

The speed gets smaller and smaller, but it never becomes exactly zero.

@@FIG_SPEED@@

### Step 2: the distance, and the "multiply and subtract" trick

The ball moves v₀ in the first cycle, v₀·d in the second, v₀·d² in the third, and so on. So the distance after n cycles is v₀ times this sum:

@@EQ_SUM_S@@

Adding many terms is slow. Here is a trick to add them all at once. Multiply the whole sum by d:

@@EQ_SUM_DS@@

Now subtract the second line from the first. Almost every term appears in both lines, so they cancel. Only the first term of S and the last term of dS survive:

@@EQ_SUM_SUB@@

That is the whole proof. ∎ Multiply by v₀, and we get the **closed form**. A closed form is a formula that gives the answer directly, without a loop. **[Derived]**

@@EQ_DIST@@

My script compares this formula with a step-by-step loop in @@CF_TESTS@@ cases. The largest difference is @@CF_ERR@@, which is just computer rounding.

@@FIG_GEO@@

### Step 3: the ceiling

When n gets very large, dⁿ gets close to zero. So the distance gets close to a fixed number. **[Derived]**

@@EQ_CEIL@@

So with the top speed of @@BALL_VMAX@@ and decay @@BALL_DECAY@@, a ball can never roll more than **@@CEILING@@ m** in my toy (no noise, no players in the way). When I first saw this, I did not believe it. So I made the script check it with a long loop.

One honest detail: one push from rest is limited by the acceleration cap of @@BALL_AMAX@@. A ball kicked from rest at that speed stops at @@CEIL_REST@@ m. The @@CEILING@@ m case needs a ball that already moves at the top speed.

The same idea gives a handy rule. The distance still left to roll is always the current speed times @@REMAIN_FACTOR@@: **[Derived]**

@@EQ_REMAIN@@

@@FIG_DIST@@

### Step 4: when is the ball "slow"? Logarithms

Let me call a ball "slow" when its speed is below @@SLOW@@ per cycle (my own choice). We need v₀·dⁿ < s. Take the logarithm of both sides. A logarithm turns "power" into "times", so we can get n down from the top. Careful: ln d is negative, so the inequality sign flips. **[Derived]**

@@EQ_SLOW@@

For a ball at @@BALL_VMAX@@, the right side is @@N_SLOW_EXACT@@, so the ball is slow from cycle **@@N_SLOW@@** (about @@T_SLOW@@ s). By then it has already rolled @@DIST_SLOW@@ m, which is @@PCT_SLOW@@% of the ceiling.

A nice way to feel this is the **half-life**: how many cycles until the speed is halved. **[Derived]**

@@EQ_HALF@@

For the ball, h ≈ @@HALF@@ cycles (about @@T_HALF@@ s). After one half-life the ball has covered @@HALF_PCT@@% of its total distance. After two half-lives, @@TWO_HALF_PCT@@%. For a player, h ≈ @@P_HALF@@ cycles: less than one cycle!

### Step 5: the inverse problem

Now turn the question around. A teammate stands D metres away. What kick speed do I need?

**To stop exactly at D**, use the ceiling formula backwards. **[Derived]**

@@EQ_INV_STOP@@

For D = @@D_EXAMPLE@@ m: v₀ = @@V_STOP@@.

**To arrive at D after exactly n cycles**, solve the closed form for v₀. **[Derived]**

@@EQ_INV_ARR@@

For D = @@D_EXAMPLE@@ m and n = @@N_ARRIVE@@: v₀ = @@V_ARR@@. The ball is still moving at @@V_ARR_END@@ when it arrives, so the teammate must control it.

**What is the fastest possible arrival?** Use the biggest kick from rest, @@BALL_AMAX@@, and solve for n. **[Derived]**

@@EQ_NMIN@@

For @@D_EXAMPLE@@ m the right side is @@N_MIN_EXACT@@, so the fastest arrival is **@@N_MIN@@ cycles**. Arriving in @@N_MIN_M1@@ cycles would need @@V_NMIN_M1@@, which is above the cap. And @@N_IMP@@ cycles would need @@V_IMP@@: impossible. In @@N_IMP@@ cycles, even the biggest kick only covers @@REACH_IMP@@ m.

### Step 6: why players stop almost at once

A player has decay @@PLAYER_DECAY@@. It keeps only @@PLAYER_KEEP_PCT@@% of its speed each cycle. In my toy the player pushes with the full acceleration @@PLAYER_AMAX@@ every cycle. Then the speed cap @@PLAYER_VMAX@@ applies. **[Toy]**

@@EQ_PLAYER@@

- Cycle 1: speed @@P_V1@@.
- Cycle @@P_CAP_CYCLE@@: already at the cap, @@PLAYER_VMAX@@.

Without the cap, the speed would settle where "push in" equals "decay out", at @@P_UNCAP@@. That is the same geometric sum again: 1 + d + d² + ... = 1/(1 − d) = @@P_SUM@@. So the cap really matters.

When the player stops pushing, the first move is @@P_V_AFTER@@, and the total coasting distance is only **@@P_COAST@@ m**. A ball with the same rule and the same top speed would coast @@B_COAST@@ m, about @@COAST_RATIO@@ times more. Players are like shopping trolleys on carpet. The ball is like a trolley on ice.

## Four ways to look at it

**The player:** "I stop almost at once, so I can change direction quickly. The ball doesn't. I must plan where it will be."

**The mathematician:** "Every question today was the same geometric series: speed, distance, ceiling, player top speed."

**The programmer:** "A closed form replaces a loop. I can ask 'where after 30 cycles?' with one line instead of 30 steps."

**The hardware engineer:** "Each cycle is one multiply and one add. That is a classic small circuit." (More at the end.)

## Noise: the ball wobbles

The simulator adds a small random push to the velocity every cycle. In the v19 code the push has a random direction and a random size, from zero up to r × speed. For the ball r = @@BALL_RAND@@, so up to @@NOISE_SPEED_PCT@@% of the speed. For a player r = @@PLAYER_RAND@@. **[Sim v19]**

@@EQ_NOISE@@

Note: the *size* is uniform, not the *area*. Small pushes are more common than in a uniform disc.

I kicked the ball @@N_MC@@ times in my toy, each time at @@BALL_AMAX@@ along the x-axis, and let it roll @@N_ROLL@@ cycles. Without noise it stops at @@STOP_DET@@ m. With noise, the average stop is at x = @@MEAN_X@@ m, y = @@MEAN_Y@@ m. The spread is @@SPREAD_X@@ m along the kick and @@SPREAD_Y@@ m across it.

**Can we predict the spread? [Derived, approximate]**

1. Each push has average zero, so the average stop does not move.
2. A push δ in one cycle changes every later move: δ + dδ + d²δ + ... = δ/(1 − d). The geometric series again!
3. One push of size up to r·s, with a uniform size, has an average squared size of (r·s)²/3. Half of that goes into each direction.
4. Independent random pushes add up through their *squares*. The speeds are v₀·dᵏ, so the squares give 1 + d² + d⁴ + ... = 1/(1 − d²).
5. Take the square root:

@@EQ_SPREAD@@

The formula gives @@SPREAD_PRED@@ m. It is approximate, because the speeds themselves are a bit noisy. The Monte Carlo test agrees within a few percent. (Monte Carlo means "try many random cases and look at the results".)

@@FIG_CLOUD@@

## The kick: only the part I can read

My source gives the kick formula, but part of it is garbled. I can read the *size* of the kick acceleration. I cannot read the *direction* part, so I leave it out. This is from my source; please check it in the manual. **[Sim v19, from my source]**

@@EQ_KICK@@

- P is the kick power.
- k_kick = @@KICK_RATE@@.
- α (alpha) is the angle between where the body faces and where the ball is, from 0 to π.
- g is the gap between the player and the ball. m = @@KICK_MARGIN@@ m is the kickable margin: how far the ball can be and still be kicked.

So a ball straight ahead and touching gets the full kick. A ball behind you and at the edge of reach gets only @@FACTOR_MIN_PCT@@%. With my toy maximum power P = @@KICK_POWER_TOY@@ (not from my source), the kick ranges from @@KICK_MAX@@ down to @@KICK_MIN@@.

@@FIG_KICK@@

**Stamina, in one paragraph.** Running costs energy, called stamina. When stamina gets low, the player's *effort* can drop, and pushes get weaker. In the v19 code, effort drops by @@EFFORT_DEC@@ at a time. My toy player has endless energy, so this part ignores stamina.

## Common mistakes

- **"It never stops, so it rolls forever."** The speed never reaches zero, but the *distance* has a ceiling.
- **"Every kick can reach @@CEILING@@ m."** From rest, one kick only reaches @@CEIL_REST@@ m in my toy.
- **"Off by one cycle."** Check your indexing: is v₀ the speed before or after the first decay?
- **"Players move like the ball."** Decay @@PLAYER_DECAY@@ versus @@BALL_DECAY@@ is a huge difference.
- **"Noise averages out, so ignore it."** The average stays, but the stopping points spread out.

## What we learned

- Speed after n cycles is v₀·dⁿ. Distance is a geometric series with the closed form v₀(1 − dⁿ)/(1 − d).
- The ceiling v₀/(1 − d) gives @@CEILING@@ m for the ball and only @@P_COAST@@ m of coasting for a player.
- Logarithms answer "how many cycles?", and the same series predicts how noise spreads the stopping point.

## Try it yourself

1. What kick speed stops the ball at exactly @@T1_DIST@@ m?
2. A ball rolls at @@T2_SPEED@@. From which cycle is it slower than @@SLOW@@?
3. If the ball decay were @@T3_DECAY@@, what would the ceiling be at top speed?
4. If the player decay were @@T4_DECAY@@, how far would a player coast from top speed?

The script prints all four answers at the end. Code: @@REPO_URL@@

## Hardware teaser (a HYPOTHESIS, not a measurement)

Each cycle the ball does "position += velocity; velocity ×= decay". On a chip, this is a **multiply-accumulate** loop. Many FPGA designs use **fixed-point** numbers: an integer that counts small steps.

In @@FX_BITS@@-bit fixed point with @@FX_FRAC_D@@ fraction bits (format Q@@FX_INT_D@@.@@FX_FRAC_D@@), the decay is stored as the integer @@DQ@@:

@@EQ_FIXED@@

The error is @@DQ_ERR@@. Tiny? It moves the @@CEILING@@ m ceiling to @@CEIL_Q@@ m, only @@CEIL_SHIFT_MM@@ mm. But rounding *during* the loop matters more. I stored the speed with @@FX_FRAC_V@@ fraction bits (steps of @@FX_STEP_V_MM@@ mm), so the kick @@BALL_AMAX@@ becomes @@V0_INT@@ steps:

- **Round down** after each multiply: the ball stops after @@FLOOR_CYCLES@@ cycles at @@FLOOR_DIST@@ m, @@FLOOR_SHORT_CM@@ cm short of the exact @@FLOAT_DIST@@ m.
- **Round to nearest**: the speed gets stuck at @@ROUND_STUCK@@ steps and never reaches zero! The ball creeps @@ROUND_CREEP_MM@@ mm per cycle: @@ROUND_D1@@ m after @@FX_LONG_1@@ cycles, @@ROUND_D2@@ m after @@FX_LONG_2@@.

The position also needs more than @@FX_BITS@@ bits, so my toy uses a @@ACC_BITS@@-bit register. My hypothesis: on my PYNQ-Z2, this loop could run in a very small circuit, but the rounding mode must be chosen on purpose. I have not built or measured this yet.

## Next time

Now we know where the ball will be at every cycle. In **Part 3: "Can I Reach the Ball, and When?"** we race a player against the ball and look for the first cycle where the player wins.

## What I am not sure about

- The update order (move first, then decay) is my assumption. If the real code is different, my answers may be off by one cycle.
- My player pushes with full acceleration every cycle. I ignore dash power, turning, the kickable margin in movement, and stamina.
- I left out the kick direction, and the maximum kick power @@KICK_POWER_TOY@@ is my own toy value.
- My spread formula is approximate. My toy has no collisions, no wind and no other players.

## References

- RoboCup Soccer Simulator contributors. (2024). *rcssserver-19.0.0*. GitHub software release, published 25 March 2024. @@SERVER_REPO_URL@@
- RoboCup Soccer Simulator maintainers. (n.d., living documentation). "4. Soccer Server." In *The RoboCup Soccer Simulator Users Manual*. @@MANUAL_URL@@
"""

# continues build_part2.py after run_sanity_checks
# =====================================================================
# LATEX (raw strings, KaTeX-safe, no "{{" or "{%" anywhere)
# =====================================================================
def build_latex(r):
    """Return dict: placeholder key -> LaTeX string. Numbers come from code."""
    d = BALL_DECAY
    lx = {}
    lx["EQ_UPDATE"] = r"x_{t+1} = x_t + v_t, \qquad v_{t+1} = d \cdot v_t"
    lx["EQ_SPEED"] = r"v_n = v_0 \cdot d^{n}"
    lx["EQ_SUM_S"] = r"S = 1 + d + d^{2} + \dots + d^{n-1}"
    lx["EQ_SUM_DS"] = r"d \cdot S = d + d^{2} + \dots + d^{n-1} + d^{n}"
    lx["EQ_SUM_SUB"] = (r"S - d \cdot S = 1 - d^{n} \quad \Longrightarrow \quad "
                        r"S = \frac{1 - d^{n}}{1 - d}")
    lx["EQ_DIST"] = r"x_n = v_0 \cdot \frac{1 - d^{n}}{1 - d}"
    lx["EQ_CEIL"] = (r"x_{\infty} = \frac{v_0}{1 - d} = \frac{" + f"{BALL_SPEED_MAX:.1f}"
                     + "}{" + g3(1 - d) + "} = " + g3(r["ceiling"]) + r"\ \mathrm{m}")
    lx["EQ_REMAIN"] = (r"x_{\infty} - x_n = \frac{v_n}{1 - d} \approx "
                       + g3(1 / (1 - d)) + r" \cdot v_n")
    lx["EQ_SLOW"] = r"v_0 \cdot d^{n} < s \iff n > \frac{\ln(s / v_0)}{\ln d}"
    lx["EQ_HALF"] = r"d^{h} = \frac{1}{2} \iff h = \frac{\ln 2}{-\ln d}"
    lx["EQ_INV_STOP"] = r"v_0 = D \cdot (1 - d)"
    lx["EQ_INV_ARR"] = r"v_0 = \frac{D \cdot (1 - d)}{1 - d^{n}}"
    lx["EQ_NMIN"] = (r"n_{\min} = \left\lceil \frac{\ln(1 - D(1 - d) / a_{\max})}"
                     r"{\ln d} \right\rceil")
    lx["EQ_PLAYER"] = (r"u_t = \min(v_t + a,\ v_{\max}), \qquad x_{t+1} = x_t + u_t, "
                       r"\qquad v_{t+1} = d_p \cdot u_t")
    lx["EQ_NOISE"] = (r"\tilde{v} = \bar{v} + R \cdot (\cos\Theta, \sin\Theta), \quad "
                      r"R \sim U[0,\ r \lVert \bar{v} \rVert], \quad \Theta \sim U[-\pi, \pi]")
    lx["EQ_SPREAD"] = (r"\sigma_{\mathrm{stop}} \approx \frac{r \cdot v_0}"
                       r"{(1 - d)\sqrt{6\,(1 - d^{2})}}")
    lx["EQ_KICK"] = (r"\lVert a_{\mathrm{kick}} \rVert = P \cdot k_{\mathrm{kick}} \cdot \left(1 - "
                     + g3(KICK_ANGLE_W) + r"\,\frac{\alpha}{\pi} - "
                     + g3(KICK_GAP_W) + r"\,\frac{g}{m}\right)")
    lx["EQ_FIXED"] = (g3(d) + r" \approx \frac{" + str(r["dq"]) + "}{2^{" + str(FX_FRAC_D)
                      + "}} = " + f"{r['dq_val']:.9f}")
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
# FIGURES (one function per figure; each takes path and results)
# =====================================================================
def power_label(k):
    """1, d, d², d³ ... as text."""
    return "1" if k == 0 else ("d" if k == 1 else "d" + str(k).translate(SUP))


def fig_speed(path, res):
    """Figure 1: speed per cycle, ball (left) and player (right)."""
    fig, (a1, a2) = new_figure(height_in=4.6, ncols=2)
    n = np.arange(0, 61)
    a1.plot(n, closed_speed(BALL_SPEED_MAX, BALL_DECAY, n), color=BLUE, lw=3, label="ball")
    a1.axhline(SLOW_SPEED, color=GREY, ls="--", lw=2, label="'slow' (toy)")
    a1.axvline(res["n_slow"], color=VERMILLION, ls=":", lw=3,
               label=f"slow at cycle {res['n_slow']}")
    a1.set_xlabel("cycle n")
    a1.set_ylabel("speed (m per cycle)")
    a1.set_title(f"Ball, decay {g3(BALL_DECAY)}")
    a1.legend(frameon=False)
    n_dash, n_coast = 5, 10
    moving, _ = player_run_loop(n_dash, n_coast, PLAYER_ACCEL_MAX, PLAYER_DECAY,
                                PLAYER_SPEED_MAX)
    c = np.arange(1, n_dash + n_coast + 1)
    a2.plot(c, moving, color=ORANGE, lw=3, marker="o", ms=7, label="player (toy)")
    a2.axvline(n_dash + 0.5, color=GREY, ls="--", lw=2)
    a2.text(n_dash + 0.8, PLAYER_SPEED_MAX * 0.9, "stops\npushing", fontsize=12)
    a2.set_xlabel("cycle n")
    a2.set_title(f"Player, decay {g3(PLAYER_DECAY)}")
    a2.set_ylim(0, PLAYER_SPEED_MAX * 1.15)
    a2.legend(frameon=False, loc="lower left")
    save_figure(fig, path)


def fig_dist(path, res):
    """Figure 2: distance per cycle with the ceiling."""
    fig, ax = new_figure(height_in=4.8)
    n = np.arange(0, 101)
    ax.plot(n, closed_distance(BALL_SPEED_MAX, BALL_DECAY, n), color=BLUE, lw=3,
            label=f"start speed {BALL_SPEED_MAX:.1f}")
    ax.plot(n, closed_distance(BALL_ACCEL_MAX, BALL_DECAY, n), color=GREEN, lw=3, ls="--",
            label=f"kick from rest {BALL_ACCEL_MAX:.1f}")
    ax.axhline(res["ceiling"], color=BLUE, lw=1.5, ls=":")
    ax.axhline(res["ceil_rest"], color=GREEN, lw=1.5, ls=":")
    ax.text(101, res["ceiling"], f"{g3(res['ceiling'])} m", va="center", fontsize=13)
    ax.text(101, res["ceil_rest"], f"{g3(res['ceil_rest'])} m", va="center", fontsize=13)
    ax.axvline(res["half"], color=VERMILLION, ls=":", lw=3,
               label=f"one half-life ({res['half']:.1f} cycles)")
    ax.set_xlim(0, 112)
    ax.set_ylim(0, res["ceiling"] * 1.12)
    ax.set_xlabel("cycle n")
    ax.set_ylabel("distance rolled (m)")
    ax.set_title("The distance has a ceiling: v₀ / (1 − d)")
    ax.legend(frameon=False, loc="lower right")
    save_figure(fig, path)


def fig_geo(path, res):
    """Figure 3: the multiply-and-subtract trick as bars."""
    d, n = PICTURE_DECAY, PICTURE_TERMS
    fig, (a1, a2) = new_figure(height_in=5.8, nrows=2, sharex=True)
    k_top, k_bot = np.arange(0, n), np.arange(1, n + 1)
    a1.bar(k_top, d ** k_top, color=[BLUE] + [LIGHT] * (n - 1), edgecolor=BLACK, lw=1.5)
    a2.bar(k_bot, d ** k_bot, color=[LIGHT] * (n - 1) + [VERMILLION], edgecolor=BLACK, lw=1.5)
    for ax, ks in ((a1, k_top), (a2, k_bot)):
        for k in ks:
            ax.text(k, d ** k + 0.04, power_label(k), ha="center", fontsize=14)
        ax.set_ylim(0, 1.25)
        ax.set_yticks([])
    a1.set_title(f"S = 1 + d + … + {power_label(n - 1)}   (picture uses d = {g3(d)})")
    a2.set_title("d·S = the same bars, one step to the right")
    a2.set_xticks(range(0, n + 1))
    a2.set_xlabel("grey bars cancel:  S − d·S = 1 − " + power_label(n))
    save_figure(fig, path)


def fig_cloud(path, res):
    """Figure 4: noisy stopping points and the predicted spread."""
    stops, sp, x0 = res["stops"], res["spread_pred"], res["stop_det"]
    fig, (a1, a2) = new_figure(height_in=4.8, ncols=2)
    a1.scatter(stops[:, 0], stops[:, 1], s=4, alpha=0.3, color=BLUE)
    a1.add_patch(Circle((x0, 0), 2 * sp, fill=False, edgecolor=VERMILLION, lw=3,
                        label="2σ (formula)"))
    a1.plot(x0, 0, marker="x", color=BLACK, ms=14, mew=3, ls="none", label="no noise")
    a1.set_aspect("equal")
    a1.set_xlim(x0 - 4.5 * sp, x0 + 4.5 * sp)
    a1.set_ylim(-4.5 * sp, 4.5 * sp)
    a1.set_xlabel("x along kick (m)")
    a1.set_ylabel("y across (m)")
    a1.set_title(f"{N_MC:,} noisy kicks")
    a1.legend(frameon=False, loc="lower left", fontsize=11)
    a2.hist(stops[:, 0], bins=40, density=True, color=SKY, edgecolor="white")
    xs = np.linspace(x0 - 4 * sp, x0 + 4 * sp, 300)
    a2.plot(xs, np.exp(-0.5 * ((xs - x0) / sp) ** 2) / (sp * math.sqrt(2 * math.pi)),
            color=VERMILLION, lw=3, label="formula")
    a2.set_xlabel("stop x (m)")
    a2.set_ylabel("share")
    a2.set_title("Along the kick")
    a2.legend(frameon=False, loc="upper left", fontsize=11)
    save_figure(fig, path)


def fig_kick(path, res):
    """Figure 5: readable kick size over angle and gap (toy max power)."""
    alpha_deg = np.linspace(0, 180, 181)
    gap = np.linspace(0, KICK_MARGIN, 141)
    A, G = np.meshgrid(np.radians(alpha_deg), gap)
    K = KICK_POWER_TOY * KICK_RATE * kick_factor(A, G)
    fig, ax = new_figure(height_in=5.0)
    pc = ax.pcolormesh(alpha_deg, gap, K, cmap="cividis", shading="auto")
    cb = fig.colorbar(pc, ax=ax)
    cb.set_label("kick size (toy max power)")
    levels = np.linspace(res["kick_min"], res["kick_max"], 6)[1:-1]
    cs = ax.contour(alpha_deg, gap, K, levels=levels, colors="white", linewidths=2)
    ax.clabel(cs, fmt="%.2f", fontsize=12)
    ax.set_xlabel("angle to ball α (degrees)")
    ax.set_ylabel("gap to ball g (m)")
    ax.set_title("Kick size, readable part only\n(from my source, check it)")
    save_figure(fig, path)


_CEIL_TXT = g3(stop_distance(BALL_SPEED_MAX, BALL_DECAY))
FIGURES = [
    {"key": "FIG_SPEED", "file": "fig2_1_speed.png", "func": fig_speed,
     "alt": "Left: the ball speed falls slowly along a smooth curve and crosses a dashed "
            "slow line. Right: the player speed jumps to the cap and drops almost at once "
            "after it stops pushing.",
     "caption": "Figure 1. Speed per cycle. The ball keeps " + g3(BALL_DECAY * 100)
                + "% each cycle, the player only " + g3(PLAYER_DECAY * 100) + "%. Toy model."},
    {"key": "FIG_DIST", "file": "fig2_2_distance.png", "func": fig_dist,
     "alt": "Two rising curves of distance against cycle that flatten under dotted "
            "ceiling lines, with a vertical line at one half-life.",
     "caption": "Figure 2. The distance grows but never passes v0 / (1 − d), which is "
                + _CEIL_TXT + " m at top speed. Toy model, no noise."},
    {"key": "FIG_GEO", "file": "fig2_3_geometric.png", "func": fig_geo,
     "alt": "Two rows of shrinking bars. The bottom row is the top row moved one step "
            "right. Grey bars match and cancel, leaving one blue bar and one red bar.",
     "caption": "Figure 3. The multiply and subtract trick. Only the first bar of S and "
                "the last bar of d times S survive."},
    {"key": "FIG_CLOUD", "file": "fig2_4_noise_cloud.png", "func": fig_cloud,
     "alt": "Left: a round cloud of blue stopping points around a black cross, with a red "
            "circle. Right: a histogram of stopping positions with a red bell curve on top.",
     "caption": "Figure 4. Stopping points of " + f"{N_MC:,}" + " noisy kicks in my toy. "
                "The red curves come from the spread formula."},
    {"key": "FIG_KICK", "file": "fig2_5_kick_size.png", "func": fig_kick,
     "alt": "A heat map of kick size. It is brightest at angle zero and gap zero, and "
            "darkest at angle 180 degrees and the largest gap.",
     "caption": "Figure 5. Readable part of the kick formula. The maximum power is my toy "
                "value. The kick direction is left out on purpose."},
]


def check_figure_files(fig_dir):
    """After drawing: every PNG exists, is 1600 px wide, and has safe text."""
    for f in FIGURES:
        path = fig_dir / f["file"]
        check(path.exists(), f"{f['file']} exists")
        check(plt.imread(str(path)).shape[1] == FIG_WIDTH_PX,
              f"{f['file']} is {FIG_WIDTH_PX} px wide")
        check(not any(ch in f["alt"] + f["caption"] for ch in "[]*"),
              f"{f['file']}: alt text and caption are Markdown-safe")


# =====================================================================
# ARTICLE BUILDER
# =====================================================================
FORBIDDEN = [r"\[\[", r"TODO", r"\[add link", r"author fills in"]


def header(target):
    if target == "devto":
        lines = ["---",
                 'title: "' + TITLE + '"',
                 "published: " + ("true" if PUBLISHED else "false"),
                 'description: "' + DESCRIPTION + '"',
                 "tags: " + ", ".join(TAGS),
                 "series: " + SERIES,
                 "# cover_image: " + BASE_URL + "/fig2_2_distance.png",
                 "---", ""]
    else:
        lines = ["# " + TITLE, ""]
    return "\n".join(lines) + "\n"


def figure_md(fig, target):
    """Image line + italic caption. dev.to gets absolute URLs only."""
    url = (BASE_URL + "/" if target == "devto" else "figures/") + fig["file"]
    return "![" + fig["alt"] + "](" + url + ")\n*" + fig["caption"] + "*"


def build_article(target, values, latex):
    text = TEMPLATE
    for key, val in values.items():
        text = text.replace("@@" + key + "@@", val)
    for key, lx in latex.items():
        text = text.replace("@@" + key + "@@", math_block(lx, target))
    for fig in FIGURES:
        text = text.replace("@@" + fig["key"] + "@@", figure_md(fig, target))
    leftover = sorted(set(re.findall(r"@@[A-Z0-9_]+@@", text)))
    if leftover:
        raise RuntimeError(target + ": unfilled placeholders: " + ", ".join(leftover))
    for pat in FORBIDDEN:
        if re.search(pat, text, flags=re.IGNORECASE):
            raise RuntimeError(target + ": empty slot found: " + pat)
    return header(target) + text


# =====================================================================
# MAIN
# =====================================================================
def main():
    set_style()

    print("Step 1/3: sanity checks")
    try:
        res = run_sanity_checks()
        latex = build_latex(res)
        for key, lx in latex.items():
            check("{{" not in lx and "{%" not in lx, f"LaTeX {key} is safe for dev.to")
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
        fig["func"](fig_dir / fig["file"], res)
    n_before = len(CHECK_LOG)
    try:
        check_figure_files(fig_dir)
    except AssertionError as err:
        print("\nFIGURE CHECK FAILED: " + str(err))
        print("Stopping. No article was written.")
        sys.exit(1)
    print(f"  {len(CHECK_LOG) - n_before} figure checks passed.")

    print("\nStep 3/3: article")
    values = compute_numbers(res)
    try:
        texts = {t: build_article(t, values, latex) for t in TARGET_FILES}
    except RuntimeError as err:
        print("\nARTICLE CHECK FAILED: " + str(err))
        print("Stopping. No article was written.")
        sys.exit(1)
    for target, filename in TARGET_FILES.items():
        path = out / filename
        path.write_text(texts[target], encoding="utf-8")
        print(f"  wrote {path} ({len(texts[target].split()):,} words incl. markup)")

    print("\nAnswers to 'Try it yourself':")
    print(f"  1. Stop at {g3(T1_DIST)} m: kick speed {res['t1']:.2f}")
    print(f"  2. Speed {g3(T2_SPEED)}: slower than {g3(SLOW_SPEED)} from cycle {res['t2']}")
    print(f"  3. Decay {g3(T3_DECAY)}: ceiling {g3(res['t3'])} m at top speed")
    print(f"  4. Player decay {g3(T4_DECAY)}: coasts {res['t4']:.3f} m from top speed")

    if not VERIFIED_ITEMS:
        print("\nNOTE: VERIFIED_ITEMS is empty, so the article says the numbers are not yet "
              "checked against the original source.")


if __name__ == "__main__":
    main()

