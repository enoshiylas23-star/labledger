import hashlib
import math
import random
import re

INSTRUMENTS = {
    "UV-1900i": {
        "type": "Double-beam UV-Vis", "range": "190 - 1100 nm", "bandwidth": "1.0 nm fixed",
        "detectors": "Photomultiplier tube", "photon_range": "-3.0 to 3.0 A",
        "wl_accuracy": 0.5, "stray": 0.004, "noise": 0.0016,
        "desc": "Touch-screen bench workhorse for QC pass/fail testing",
    },
    "UV-2600i": {
        "type": "Single-beam UV-Vis", "range": "185 - 1100 nm", "bandwidth": "0.1 - 5.0 nm variable",
        "detectors": "Photomultiplier tube", "photon_range": "-4.0 to 4.0 A",
        "wl_accuracy": 0.3, "stray": 0.002, "noise": 0.0009,
        "desc": "Variable bandwidth research workhorse with accessory support",
    },
    "UV-2700": {
        "type": "Double monochromator UV-Vis", "range": "185 - 900 nm", "bandwidth": "0.1 - 5.0 nm variable",
        "detectors": "Photomultiplier tube", "photon_range": "-6.0 to 8.0 A",
        "wl_accuracy": 0.1, "stray": 0.0005, "noise": 0.0005,
        "desc": "Double monochromator for high-absorbance work up to 8 Abs",
    },
    "UV-3600 Plus": {
        "type": "UV-Vis-NIR spectrophotometer", "range": "185 - 3300 nm", "bandwidth": "0.1 - 32 nm variable",
        "detectors": "PMT + cooled InGaAs + cooled PbS", "photon_range": "-6.0 to 6.0 A",
        "wl_accuracy": 0.5, "stray": 0.001, "noise": 0.0010,
        "desc": "Three-detector UV-Vis-NIR for materials and coatings",
    },
    "SolidSpec-3700": {
        "type": "UV-Vis-NIR with integrating sphere", "range": "300 - 2600 nm (DUV option 175 nm)",
        "bandwidth": "0.1 - 32 nm variable", "detectors": "PMT + InGaAs + PbS, integrating sphere",
        "photon_range": "-4.0 to 4.0 A", "wl_accuracy": 0.8, "stray": 0.003, "noise": 0.0022,
        "desc": "Solids, films, powders and reflectance measurement",
    },
}

COMPOUNDS = [
    {"name": "Caffeine", "formula": "C8H10N4O2", "cas": "58-08-2", "lambda_max": 272, "eps": 9700,
     "solvent": "Water", "use": "Pharmaceutical assay (USP)", "method_wl": 272,
     "bands": [(205, 0.35, 9), (244, 0.55, 15), (272, 1.0, 13)],
     "notes": "Band at 272 nm is the official assay wavelength; 205 nm band unusable in phosphate buffers."},
    {"name": "Paracetamol", "formula": "C8H9NO2", "cas": "103-90-2", "lambda_max": 243, "eps": 11700,
     "solvent": "0.1 M HCl", "use": "Pharmaceutical assay", "method_wl": 243,
     "bands": [(243, 1.0, 11), (292, 0.16, 17)],
     "notes": "Lambda max shifts to 257 nm at pH 9 - always state the solvent."},
    {"name": "Aspirin", "formula": "C9H8O4", "cas": "50-78-2", "lambda_max": 237, "eps": 1100,
     "solvent": "Ethanol", "use": "Pharmaceutical assay / hydrolysis monitoring", "method_wl": 237,
     "bands": [(237, 1.0, 9)],
     "notes": "Salicylic acid impurity absorbs at 303 nm - monitor both wavelengths."},
    {"name": "Salicylic acid", "formula": "C7H6O3", "cas": "69-72-7", "lambda_max": 303, "eps": 6500,
     "solvent": "Ethanol", "use": "Aspirin impurity test", "method_wl": 303,
     "bands": [(214, 1.0, 10), (240, 0.45, 12), (303, 0.85, 22)],
     "notes": "Directly monitors aspirin hydrolysis; fluorescent above 400 nm."},
    {"name": "Benzoic acid", "formula": "C7H6O2", "cas": "65-85-0", "lambda_max": 230, "eps": 10600,
     "solvent": "Ethanol", "use": "Food preservative assay", "method_wl": 230,
     "bands": [(230, 1.0, 9)],
     "notes": "Common in soft-drink QC; acidify sample to shift to molecular form."},
    {"name": "Phenol", "formula": "C6H6O", "cas": "108-95-2", "lambda_max": 270, "eps": 1450,
     "solvent": "Water", "use": "Environmental / water analysis", "method_wl": 270,
     "bands": [(211, 0.8, 8), (270, 1.0, 14)],
     "notes": "4-aminoantipyrine colour method preferred below 0.5 mg/L."},
    {"name": "Nitrate ion", "formula": "NO3-", "cas": "14797-55-8", "lambda_max": 200, "eps": 5000,
     "solvent": "Water", "use": "Environmental water (EPA method reads 220 nm)", "method_wl": 220,
     "bands": [(200, 1.0, 12), (302, 0.10, 20)],
     "notes": "Read at 220 nm; correct for dissolved organic carbon at 275 nm."},
    {"name": "Methylene blue", "formula": "C16H18ClN3S", "cas": "61-73-4", "lambda_max": 664, "eps": 95000,
     "solvent": "Water", "use": "Dye assay, decolourisation kinetics", "method_wl": 664,
     "bands": [(664, 1.0, 12), (610, 0.22, 10)],
     "notes": "Dimer band at 610 nm grows above 10 uM - keep dilute."},
    {"name": "Sunset yellow FCF", "formula": "C16H10N2Na2O7S2", "cas": "1934-21-0", "lambda_max": 482,
     "eps": 27000, "solvent": "Water", "use": "Food colour assay (EU/US limits)", "method_wl": 482,
     "bands": [(380, 0.16, 24), (482, 1.0, 32)],
     "notes": "HPLC confirmation required above 100 mg/kg; pH shifts the band."},
    {"name": "Riboflavin (B2)", "formula": "C17H20N4O6", "cas": "83-88-5", "lambda_max": 445, "eps": 12500,
     "solvent": "0.1 M NaOH", "use": "Vitamin assay, photostability studies", "method_wl": 445,
     "bands": [(223, 0.9, 11), (267, 0.7, 13), (373, 0.5, 16), (445, 1.0, 26)],
     "notes": "Photo-labile: measure in amber glass within 30 min of preparation."},
    {"name": "Potassium permanganate", "formula": "KMnO4", "cas": "7722-64-7", "lambda_max": 525, "eps": 3000,
     "solvent": "Water", "use": "Oxidimetry, water permanganate index", "method_wl": 525,
     "bands": [(525, 1.0, 17)],
     "notes": "MnO4- slowly decomposes in light - prepare fresh daily."},
    {"name": "Copper(II) sulfate", "formula": "CuSO4", "cas": "7758-98-7", "lambda_max": 810, "eps": 12,
     "solvent": "Water", "use": "Beer-Lambert teaching, electrodeposition baths", "method_wl": 810,
     "bands": [(810, 1.0, 80)],
     "notes": "Weak d-d band: use long path length (5-10 cm) cells."},
    {"name": "Toluene", "formula": "C7H8", "cas": "108-88-3", "lambda_max": 268, "eps": 260,
     "solvent": "Hexane", "use": "Solvent purity / GC-UV cross-check", "method_wl": 268,
     "bands": [(254, 0.62, 3.5), (261, 0.82, 3.5), (268, 1.0, 3.5)],
     "notes": "Vibrational fine structure - needs <= 1 nm bandwidth to resolve."},
    {"name": "Naphthalene", "formula": "C10H8", "cas": "91-20-3", "lambda_max": 275, "eps": 360,
     "solvent": "Ethanol", "use": "PAH screening, standards preparation", "method_wl": 275,
     "bands": [(221, 1.0, 7), (275, 0.7, 5), (312, 0.3, 5)],
     "notes": "Fine structure collapses in polar solvents."},
]

SPEED_FACTOR = {"slow": 0.6, "medium": 1.0, "fast": 1.9}


def compound(name):
    for c in COMPOUNDS:
        if c["name"] == name:
            return c
    return COMPOUNDS[0]


def gauss(x, mu, sigma):
    return math.exp(-((x - mu) ** 2) / (2 * sigma * sigma))


def eps_at(c, wl):
    v = 0.0
    for mu, rel, sig in c["bands"]:
        v += rel * gauss(wl, mu, sig)
    return c["eps"] * v


def default_conc(c):
    return max(1.0, min(500.0, 0.8 * 1e6 / max(c["eps"], 1)))


def spectrum_points(c, wl_start, wl_end, step, conc_m, path_cm):
    pts = []
    wl = wl_start
    while wl <= wl_end + 1e-9:
        pts.append((round(wl, 2), eps_at(c, wl) * conc_m * path_cm))
        wl += step
    return pts


def library_shape(c, wl_start, wl_end, step):
    pts = spectrum_points(c, wl_start, wl_end, step, 1.0, 1.0)
    m = max(y for _, y in pts) or 1.0
    return [(x, y / m) for x, y in pts]


def line_chart(series, xlabel, ylabel, width=780, height=300, pad=46):
    xs = [x for s in series for x, _ in s["pts"]]
    ys = [y for s in series for _, y in s["pts"]]
    if not xs:
        return ""
    xmin, xmax = min(xs), max(xs)
    ymin = min(0.0, min(ys))
    ymax = max(ys) if max(ys) > ymin else ymin + 1
    span_x = xmax - xmin or 1
    span_y = ymax - ymin or 1
    ymax += span_y * 0.06
    span_y = ymax - ymin or 1

    def sx(x):
        return pad + (x - xmin) / span_x * (width - 2 * pad)

    def sy(y):
        return height - pad - (y - ymin) / span_y * (height - 2 * pad)

    out = [f'<svg viewBox="0 0 {width} {height}" class="trace" role="img">']
    for i in range(5):
        xv = xmin + span_x * i / 4
        yv = ymin + span_y * i / 4
        gx, gy = sx(xv), sy(yv)
        out.append(f'<line x1="{gx:.1f}" y1="{pad}" x2="{gx:.1f}" y2="{height - pad}" class="grid"/>')
        out.append(f'<line x1="{pad}" y1="{gy:.1f}" x2="{width - pad}" y2="{gy:.1f}" class="grid"/>')
        out.append(f'<text x="{gx:.1f}" y="{height - pad + 16}" class="axis">{xv:.1f}</text>')
        out.append(f'<text x="{pad - 6}" y="{gy:.1f}" class="axis" text-anchor="end">{yv:.3f}</text>')
    out.append(f'<text x="{width / 2}" y="{height - 6}" class="axis" text-anchor="middle">{xlabel}</text>')
    for s in series:
        d = " ".join(("M" if i == 0 else "L") + f"{sx(x):.1f},{sy(y):.1f}" for i, (x, y) in enumerate(s["pts"]))
        dash = ' stroke-dasharray="5 4"' if s.get("dashed") else ""
        out.append(f'<path d="{d}" fill="none" stroke="{s.get("color", "#4cc2ff")}" stroke-width="{s.get("w", 1.6)}"{dash}/>')
        if s.get("marker"):
            mx = sx(s["marker"][0])
            out.append(f'<line x1="{mx:.1f}" y1="{pad}" x2="{mx:.1f}" y2="{height - pad}" class="peakline"/>')
            out.append(f'<text x="{mx:.1f}" y="{pad - 6}" class="peaklabel">{s["marker"][1]}</text>')
    lx = pad + 8
    ly = pad + 6
    for i, s in enumerate(series):
        if s.get("nodraw"):
            continue
        out.append(f'<rect x="{lx}" y="{ly + i * 16}" width="14" height="3" fill="{s.get("color", "#4cc2ff")}"/>')
        out.append(f'<text x="{lx + 20}" y="{ly + i * 16 + 5}" class="axis">{s["label"]}</text>')
    out.append("</svg>")
    return "".join(out)


def peak_pick(pts):
    best = max(pts, key=lambda p: p[1])
    i = pts.index(best)
    if 0 < i < len(pts) - 1:
        y0, y1, y2 = pts[i - 1][1], pts[i][1], pts[i + 1][1]
        den = y0 - 2 * y1 + y2
        if abs(den) > 1e-12:
            dx = 0.5 * (y0 - y2) / den
            step = pts[i + 1][0] - pts[i][0]
            return round(best[0] + dx * step, 2), round(y1 - 0.25 * (y0 - y2) * dx, 4)
    return best


def baseline_value(wl, level=1.0, wl0=200.0):
    b = 0.0012 + 0.000004 * (wl - wl0) + 0.0008 * math.exp(-((wl - 330.0) / 140.0) ** 2)
    return max(0.0, level * b)


def baseline_points(wl0, wl1, step, rng, level=1.0):
    pts = []
    wl = wl0
    while wl <= wl1 + 1e-9:
        b = baseline_value(wl, level, wl0) + rng.gauss(0, 0.00018)
        pts.append((round(wl, 2), round(max(0.0, b), 5)))
        wl += step
    return pts


def subtract_baseline(meas, base):
    bd = dict(base)
    return [(x, round(max(0.0, y - bd.get(x, 0.0)), 4)) for x, y in meas]


BASELINE_OPTIONS = [
    ("none", "None - raw spectra"),
    ("blank", "Solvent blank subtraction"),
    ("endpoint", "Endpoint correction (linear, first to last point)"),
    ("autozero", "Auto-zero (subtract minimum, force A = 0)"),
]

BASELINE_LABELS = dict(BASELINE_OPTIONS)


def endpoint_baseline(meas):
    if len(meas) < 2:
        return []
    (x0, y0), (x1, y1) = meas[0], meas[-1]
    span = (x1 - x0) or 1.0
    return [(x, y0 + (y1 - y0) * (x - x0) / span) for x, _ in meas]


def autozero_baseline(meas):
    if not meas:
        return []
    m = min(y for _, y in meas)
    return [(x, m) for x, _ in meas]


def baseline_curve(method, meas, wl0, wl1, step, rng):
    if method == "blank":
        return baseline_points(wl0, wl1, step, rng)
    if method == "endpoint":
        return endpoint_baseline(meas)
    if method == "autozero":
        return autozero_baseline(meas)
    return None


def interp_curve(curve, wl):
    if not curve:
        return 0.0
    if wl <= curve[0][0]:
        return curve[0][1]
    if wl >= curve[-1][0]:
        return curve[-1][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if x0 <= wl <= x1:
            return y0 + (y1 - y0) * (wl - x0) / ((x1 - x0) or 1.0)
    return curve[-1][1]


ATOMIC_MASS = {
    "H": 1.008, "B": 10.81, "C": 12.011, "N": 14.007, "O": 15.999, "F": 18.998,
    "Na": 22.990, "Mg": 24.305, "Al": 26.982, "Si": 28.085, "P": 30.974, "S": 32.06,
    "Cl": 35.45, "K": 39.098, "Ca": 40.078, "Ti": 47.867, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38, "As": 74.922,
    "Se": 78.971, "Br": 79.904, "Ag": 107.868, "Cd": 112.414, "Sn": 118.710,
    "I": 126.904, "Ba": 137.33, "Pb": 207.2, "Hg": 200.59,
}


def molar_mass(formula):
    if not formula:
        return None
    parts = re.findall(r"([A-Z][a-z]?)(\d*)", formula.replace("-", "").replace("+", ""))
    total = 0.0
    used = 0
    for sym, num in parts:
        if sym in ATOMIC_MASS:
            total += ATOMIC_MASS[sym] * (int(num) if num else 1)
            used += 1
    return round(total, 3) if used else None


UNIT_LABELS = {"uM": "uM", "mg/L": "mg/L", "ppm": "ppm"}


def convert_conc(uM, units, mw):
    if units in ("mg/L", "ppm") and mw:
        return round(uM * mw / 1000.0, 4)
    return round(uM, 3)


def detect_peaks(pts, threshold=0.005, min_span=4.0, comp=None):
    n = len(pts)
    maxima = []
    for i in range(1, n - 1):
        y0, y1, y2 = pts[i - 1][1], pts[i][1], pts[i + 1][1]
        if y1 > y0 + 1e-12 and y1 >= y2 and y1 >= threshold:
            maxima.append(i)
    chosen = []
    for i in maxima:
        if chosen and abs(pts[i][0] - pts[chosen[-1]][0]) < min_span:
            if pts[i][1] > pts[chosen[-1]][1]:
                chosen[-1] = i
        else:
            chosen.append(i)
    peaks = []
    for idx in chosen:
        left = idx
        while left > 0 and (idx - left) < 40 and pts[left - 1][1] < pts[left][1] + 1e-12:
            left -= 1
        right = idx
        while right < n - 1 and (right - idx) < 40 and pts[right + 1][1] < pts[right][1] + 1e-12:
            right += 1
        step = pts[1][0] - pts[0][0] if n > 1 else 1.0
        if pts[right][0] - pts[left][0] < min_span:
            continue
        lya, ryb = pts[left][1], pts[right][1]
        dlambda = pts[right][0] - pts[left][0]
        base_at = lambda x: lya + (ryb - lya) * (x - pts[left][0]) / (dlambda or 1.0)
        region = [p for p in pts if pts[left][0] <= p[0] <= pts[right][0]]
        h = max(max(p[1] - base_at(p[0]), 0.0) for p in region)
        area = 0.0
        for p, q in zip(region, region[1:]):
            area += 0.5 * ((p[1] - base_at(p[0])) + (q[1] - base_at(q[0]))) * (q[0] - p[0])
        width = pts[right][0] - pts[left][0]
        top_wl, top_a = pts[idx][0], pts[idx][1]
        fwhm = 0.0
        half = lya + (top_a - lya) / 2.0
        for p, q in zip(region, region[1:]):
            if p[1] <= half <= q[1]:
                xa = p[0] + (half - p[1]) / (q[1] - p[1] or 1e-12) * (q[0] - p[0])
                fwhm = abs(xa - top_wl)
                break
        for p, q in zip(region, region[1:]):
            if q[1] <= half <= p[1]:
                xa = p[0] + (half - p[1]) / (q[1] - p[1] or 1e-12) * (q[0] - p[0])
                fwhm = max(fwhm, abs(xa - top_wl))
                break
        purity = _region_purity(region, base_at, top_wl, comp, step)
        if fwhm <= 0:
            fwhm = min(width, max(1.0, 2.0 * step))
        peaks.append({"wl": top_wl, "height_A": h, "area_A_nm": area,
                      "width_nm": width, "fwhm_nm": fwhm,
                      "purity": round(purity, 3), "active": False})
    peaks.sort(key=lambda p: p["wl"])
    return peaks


def _region_purity(region, base_at, top_wl, comp, step):
    mv = [p[1] - base_at(p[0]) for p in region]
    if not mv or max(mv) <= 0:
        return 0.0
    if comp is None or not region:
        f = sum(mv) * step / (max(mv) * (region[-1][0] - region[0][0]) or 1.0)
        return min(1.0, f / 0.94)
    lib = {x: max(0.0, eps_at(comp, x)) for x in [p[0] for p in region]}
    mm = [p[1] - base_at(p[0]) for p in region]
    ll = [lib[p[0]] for p in region]
    m0, l0 = sum(mm) / len(mm), sum(ll) / len(ll)
    num = sum((a - m0) * (b - l0) for a, b in zip(mm, ll))
    den = math.sqrt(sum((a - m0) ** 2 for a in mm) * sum((b - l0) ** 2 for b in ll)) or 1e-12
    return min(1.0, max(0.0, num / den))


def _weights(xs, weighting):
    if weighting == "1/x":
        return [1.0 / max(abs(x), 1e-9) for x in xs]
    if weighting == "1/x2":
        return [1.0 / max(x * x, 1e-12) for x in xs]
    return [1.0 for _ in xs]


def _solve_linear(mat, vec):
    m = [row[:] for row in mat]
    v = vec[:]
    n = len(m)
    for col in range(n):
        p = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[p] = m[p], m[col]
        v[col], v[p] = v[p], v[col]
        piv = m[col][col] or 1e-12
        for r in range(col + 1, n):
            f = m[r][col] / piv
            for c in range(col, n):
                m[r][c] -= f * m[col][c]
            v[r] -= f * v[col]
    out = [0.0] * n
    for i in reversed(range(n)):
        s = v[i] - sum(m[i][j] * out[j] for j in range(i + 1, n))
        out[i] = s / (m[i][i] or 1e-12)
    return out


def _fit_stats(xs, ys, coeffs, n_params):
    n = len(xs)
    my = sum(ys) / n
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-12
    ss_res = 0.0
    for x, y in zip(xs, ys):
        pred = coeffs[0] + coeffs[1] * x + (coeffs[2] * x * x if len(coeffs) > 2 else 0.0)
        ss_res += (y - pred) ** 2
    r2 = max(0.0, 1 - ss_res / ss_tot)
    dof = n - n_params
    syx = math.sqrt(ss_res / dof) if dof > 0 else 0.0
    return r2, syx


def lin_reg(xs, ys, weighting="none", no_intercept=False):
    n = len(xs)
    w = _weights(xs, weighting)
    if no_intercept:
        den = sum(wi * x * x for wi, x in zip(w, xs))
        slope = sum(wi * x * y for wi, x, y in zip(w, xs, ys)) / den if den else 0.0
        intercept = 0.0
    else:
        sw = sum(w)
        mx = sum(wi * x for wi, x in zip(w, xs)) / sw
        my = sum(wi * y for wi, y in zip(w, ys)) / sw
        sxx = sum(wi * (x - mx) ** 2 for wi, x in zip(w, xs))
        slope = sum(wi * (x - mx) * (y - my) for wi, x, y in zip(w, xs, ys)) / sxx if sxx else 0.0
        intercept = my - slope * mx
    r2, syx = _fit_stats(xs, ys, [intercept, slope], 1 if no_intercept else 2)
    return {"type": "linear", "coeffs": [intercept, slope], "weighting": weighting,
            "no_intercept": no_intercept,
            "eq": f"A = {intercept:.5f} + {slope:.5f} \u00b7 C" if not no_intercept
                  else f"A = {slope:.5f} \u00b7 C (zero intercept)",
            "r2": r2, "syx": syx, "n": n,
            "lod": 3.3 * syx / slope if slope else 0.0,
            "loq": 10.0 * syx / slope if slope else 0.0}


def quad_reg(xs, ys, weighting="none", no_intercept=False):
    n = len(xs)
    w = _weights(xs, weighting)
    if no_intercept:
        s2 = sum(wi * x * x for wi, x in zip(w, xs))
        s3 = sum(wi * x ** 3 for wi, x in zip(w, xs))
        s4 = sum(wi * x ** 4 for wi, x in zip(w, xs))
        t1 = sum(wi * x * y for wi, x, y in zip(w, xs, ys))
        t2 = sum(wi * x * x * y for wi, x, y in zip(w, xs, ys))
        c1, c2 = _solve_linear([[s2, s3], [s3, s4]], [t1, t2])
        coeffs = [0.0, c1, c2]
    else:
        s0 = sum(w)
        s1 = sum(wi * x for wi, x in zip(w, xs))
        s2 = sum(wi * x * x for wi, x in zip(w, xs))
        s3 = sum(wi * x ** 3 for wi, x in zip(w, xs))
        s4 = sum(wi * x ** 4 for wi, x in zip(w, xs))
        t0 = sum(wi * y for wi, y in zip(w, ys))
        t1 = sum(wi * x * y for wi, x, y in zip(w, xs, ys))
        t2 = sum(wi * x * x * y for wi, x, y in zip(w, xs, ys))
        c0, c1, c2 = _solve_linear([[s0, s1, s2], [s1, s2, s3], [s2, s3, s4]], [t0, t1, t2])
        coeffs = [c0, c1, c2]
    r2, syx = _fit_stats(xs, ys, coeffs, 2 if no_intercept else 3)
    slope_at = coeffs[1] + 2 * coeffs[2] * (max(xs) + min(xs)) / 2.0
    eq = _eq_text("quadratic", coeffs, no_intercept)
    return {"type": "quadratic", "coeffs": coeffs, "eq": eq, "r2": r2,
            "weighting": weighting, "no_intercept": no_intercept,
            "syx": syx, "n": n,
            "lod": 3.3 * syx / slope_at if slope_at else 0.0,
            "loq": 10.0 * syx / slope_at if slope_at else 0.0}


def cal_value(cal, c):
    coeffs = cal["coeffs"]
    if cal["type"] == "quadratic":
        return coeffs[0] + coeffs[1] * c + coeffs[2] * c * c
    return coeffs[0] + coeffs[1] * c


def _eq_text(cal_type, coeffs, no_intercept=False):
    if cal_type == "quadratic":
        if no_intercept:
            return f"A = {coeffs[1]:.5f} \u00b7 C + {coeffs[2]:.6f} \u00b7 C\u00b2 (zero intercept)"
        return f"A = {coeffs[0]:.5f} + {coeffs[1]:.5f} \u00b7 C + {coeffs[2]:.6f} \u00b7 C\u00b2"
    if no_intercept:
        return f"A = {coeffs[1]:.5f} \u00b7 C (zero intercept)"
    return f"A = {coeffs[0]:.5f} + {coeffs[1]:.5f} \u00b7 C"


def cal_inverse(cal, a):
    coeffs = cal["coeffs"]
    if cal["type"] == "quadratic":
        c2, c1, c0 = coeffs[2], coeffs[1], coeffs[0]
        disc = c1 * c1 - 4 * c2 * (c0 - a)
        if disc < 0 or abs(c2) < 1e-12:
            return 0.0
        lin = (a - c0) / c1 if c1 else 0.0
        r1 = (-c1 + math.sqrt(disc)) / (2 * c2)
        r2 = (-c1 - math.sqrt(disc)) / (2 * c2)
        return r1 if abs(r1 - lin) <= abs(r2 - lin) else r2
    return (a - coeffs[0]) / coeffs[1] if coeffs[1] else 0.0


def resolve_active_peak(p, comp, peaks):
    setting = p.get("active_peak", "auto")
    if setting == "manual" and p.get("active_peak_nm"):
        return round(float(p["active_peak_nm"]), 2)
    if setting == "tallest" and peaks:
        return peaks[0]["wl"] if peaks else round(float(p.get("method_wl") or comp["method_wl"]), 2)
    return round(float(p.get("method_wl") or comp["method_wl"]), 2)


def mark_active(peaks, wl):
    if not peaks:
        return peaks
    best = min(peaks, key=lambda pk: abs(pk["wl"] - wl))
    best["active"] = True
    return peaks


def apply_instrument(wl, a, inst, state, rng, speed, source):
    shift = rng.gauss(0, inst["wl_accuracy"])
    if state.get("wl_cal"):
        shift -= state["wl_cal"]
    stray = inst["stray"]
    if state.get("stray_corr"):
        stray *= 0.35
    noise = inst["noise"] * SPEED_FACTOR.get(speed, 1.0) * state.get("noise_scale", 1.0)
    if source == "physical":
        noise *= 2.2
    a_corr = -math.log10(max(10 ** (-a) + stray, 1e-12))
    a_corr += rng.gauss(0, noise) * (1 + 0.08 * a_corr)
    if source == "physical":
        a_corr += 0.00035 * max(0.0, (600.0 - wl)) / 600.0
    return max(0.0, a_corr), shift


def truth_sample(comp, conc_uM, rng, source):
    actual = conc_uM * 1e-6
    purity = 1.0
    pipet = 0.0
    if source == "physical":
        pipet = rng.gauss(0, 0.006)
        purity = rng.uniform(0.988, 0.999)
        actual *= (1 + pipet) * purity
    return actual, purity, pipet


def spectrum_from_points(pts, comp, compound_hint=None):
    wl0, wl1 = pts[0][0], pts[-1][0]
    step = max(0.1, round((wl1 - wl0) / max(1, len(pts) - 1), 3))
    est_lambda, est_amax = peak_pick(pts)
    best, score = None, -1.0
    for c2 in COMPOUNDS:
        lib = dict(library_shape(c2, wl0, wl1, step))
        m = max(y for _, y in pts) or 1
        num = vsum = lsum = 0.0
        for x, y in pts:
            ly = lib.get(x)
            if ly is None:
                continue
            a, b = y / m, ly
            num += a * b
            vsum += a * a
            lsum += b * b
        sc = num / (math.sqrt(vsum * lsum) or 1)
        if sc > score:
            best, score = c2, sc
    library_lambda = compound_hint["lambda_max"] if compound_hint else (best["lambda_max"] if best else None)
    peaks = detect_peaks(pts, threshold=0.004, min_span=4.0, comp=(compound_hint or best))
    peaks = mark_active(peaks, est_lambda)
    analysis = {
        "lambda_max_nm": est_lambda, "abs_max": est_amax,
        "identified_as": best["name"] if score > 0.90 else "no confident match",
        "match_score": round(score, 4),
        "wl_shift_mean_nm": 0.0,
        "active_peak_nm": est_lambda, "n_peaks": len(peaks),
    }
    checks = [
        {"name": "Library match", "value": f"{analysis['identified_as']} ({analysis['match_score']})",
         "limit": "> 0.900", "pass": score > 0.90},
        {"name": "Absorbance range", "value": f"{est_amax:.3f} A", "limit": "0.100 - 2.500 A",
         "pass": 0.1 <= est_amax <= 2.5},
        {"name": "Wavelength vs library", "value": f"{est_lambda:.1f} nm",
         "limit": f"± 1.0 nm of {library_lambda}", "pass": library_lambda is not None and abs(est_lambda - library_lambda) <= 1.0},
    ]
    ref = library_shape(best or COMPOUNDS[0], wl0, wl1, step) if best else []
    ref_scaled = [(x, y * est_amax) for x, y in ref]
    series = [
        {"label": "Measured (instrument)", "pts": pts, "color": "#4cc2ff",
         "marker": (est_lambda, f"{est_lambda:.1f} nm")},
        {"label": "Library reference (scaled)", "pts": ref_scaled, "color": "#ffc857", "dashed": True},
    ]
    data = {"series": series, "xlabel": "Wavelength (nm)", "ylabel": "Absorbance (A)",
            "points": pts, "peaks": peaks,
            "baseline": {"applied": False, "method": "none", "pts": []}}
    log = [{"action": "bridge.received", "detail": f"{len(pts)} points ingested from instrument driver",
            "hash": hashlib.sha256(str(len(pts)).encode()).hexdigest(), "prev": None}]
    return {"mode": "Spectrum", "data": data, "truth": None, "analysis": analysis, "checks": checks,
            "chart": line_chart(series, "Wavelength (nm)", "Absorbance (A)"), "log": log,
            "summary": f"Lambda max {est_lambda:.1f} nm, {analysis['identified_as']} (bridge data)"}


def cal_chart(cal, std_pts, unknowns):
    if not std_pts:
        return ""
    xs = [x for x, _ in std_pts]
    if cal["type"] == "quadratic":
        lo, hi = min(xs), max(xs)
        xs_curve = [lo + (hi - lo) * i / 40 for i in range(41)]
    else:
        xs_curve = [xs[0], xs[-1]]
    cal_s = [
        {"label": f"Calibration ({cal['type']})", "pts": [(x, cal_value(cal, x)) for x in xs_curve],
         "color": "#4cc2ff", "w": 2.0},
        {"label": "Standard points", "pts": std_pts, "color": "#ffc857"},
        {"label": "Unknown samples", "pts": [(u["found_uM"], u["mean_abs"]) for u in unknowns],
         "color": "#3ddc97"},
    ]
    return line_chart(cal_s, "Concentration (uM)", "Absorbance (A)")


def _resolve_units(comp, p):
    mw = molar_mass(comp.get("formula"))
    units = p.get("units") or "uM"
    if units not in UNIT_LABELS or (units != "uM" and not mw):
        units = "uM"
    return mw, units, UNIT_LABELS[units]


def quant_core(p, comp, inst, state, rng, source, scan_conc, conc_uM, path, wl0, wl1, step, speed):
    bl_method = p.get("baseline") or "none"
    scan_pts = spectrum_points(comp, wl0, wl1, step, scan_conc, path)
    scan_meas = []
    for wl, a in scan_pts:
        am, _ = apply_instrument(wl, a, inst, state, rng, speed, source)
        scan_meas.append((round(wl, 2), round(am, 4)))
    if bl_method in ("endpoint", "autozero"):
        blank_meas = []
        for wl, a in spectrum_points(comp, wl0, wl1, step, 0.0, path):
            am, _ = apply_instrument(wl, a, inst, state, rng, speed, source)
            blank_meas.append((round(wl, 2), round(am, 4)))
        bl_curve = endpoint_baseline(blank_meas) if bl_method == "endpoint" \
            else autozero_baseline(blank_meas)
    else:
        bl_curve = None
    if bl_curve is not None:
        scan_meas = subtract_baseline(scan_meas, bl_curve)
    peaks = detect_peaks(scan_meas,
                         threshold=float(p.get("peak_threshold") or 0.004),
                         min_span=float(p.get("min_peak_span") or 4.0), comp=comp)
    active_wl = resolve_active_peak(p, comp, peaks)
    peaks = mark_active(peaks, active_wl)
    meas_type = p.get("meas_type") or "height"
    if peaks:
        near = min(peaks, key=lambda pk: abs(pk["wl"] - active_wl))
        half = max(3.0, near["width_nm"] / 2.0)
    else:
        half = 8.0
    w0 = max(wl0, active_wl - half)
    w1 = min(wl1, active_wl + half)

    def bl_sub(wl, am):
        if bl_method == "blank":
            ab, _ = apply_instrument(wl, baseline_value(wl, 1.0, wl0), inst, state, rng, speed, source)
            return max(0.0, am - ab)
        if bl_curve is not None:
            return max(0.0, am - interp_curve(bl_curve, wl))
        return am

    def shot(c_uM):
        if meas_type == "area":
            grid = []
            wl = w0
            while wl <= w1 + 1e-9:
                grid.append(round(wl, 2))
                wl += step
            if len(grid) >= 2:
                vals = []
                for wl in grid:
                    a_true = eps_at(comp, wl) * c_uM * 1e-6 * path
                    am, _ = apply_instrument(wl, a_true, inst, state, rng, speed, source)
                    vals.append(bl_sub(wl, am))
                g = grid[1] - grid[0]
                return max(0.0, g * (sum(vals) - 0.5 * (vals[0] + vals[-1])))
        a_true = eps_at(comp, active_wl) * c_uM * 1e-6 * path
        am, _ = apply_instrument(active_wl, a_true, inst, state, rng, speed, source)
        return bl_sub(active_wl, am)

    built = False
    saved = p.get("calibration")
    weighting = p.get("weighting") or "none"
    no_intercept = bool(p.get("no_intercept"))
    cal_type = p.get("cal_type") or "linear"
    if saved:
        xs = [round(float(s["conc_uM"]), 2) for s in saved["standards"]]
        ys = [float(s["abs"]) for s in saved["standards"]]
        std_rows = [{"level": s.get("level", s["conc_uM"]), "conc_uM": s["conc_uM"],
                     "abs": s["abs"], "accepted": bool(s.get("accepted", True))} for s in saved["standards"]]
        cal = {"type": saved.get("cal_type", "linear"), "coeffs": list(saved["coeffs"]),
               "eq": _eq_text(saved.get("cal_type", "linear"), saved["coeffs"],
                              bool(saved.get("no_intercept"))),
               "r2": float(saved.get("r2", 1.0)), "syx": float(saved.get("syx", 0.0)),
               "lod": float(saved.get("lod", 0.0)), "loq": float(saved.get("loq", 0.0)),
               "weighting": saved.get("weighting", "none"),
               "no_intercept": bool(saved.get("no_intercept")),
               "n": len(xs)}
    else:
        levels = [float(x) for x in (p.get("std_levels") or "").split(",") if x.strip()]
        if len(levels) < 3:
            levels = [round(conc_uM * r, 2) for r in [0.0, 0.5, 0.75, 1.0, 1.25, 1.5]]
        need = 5 if cal_type == "quadratic" else 3
        if len(levels) < need:
            for extra in [round(conc_uM * 0.5, 2), round(conc_uM, 2), round(conc_uM * 1.5, 2)]:
                levels.append(extra)
        xs, ys, std_rows = [], [], []
        for lv in sorted(set(levels)):
            am = shot(lv)
            xs.append(round(lv, 2))
            ys.append(round(am, 4))
            std_rows.append({"level": round(lv, 2), "conc_uM": round(lv, 2),
                             "abs": round(am, 4), "accepted": True})
        cal = quad_reg(xs, ys, weighting, no_intercept) if cal_type == "quadratic" \
            else lin_reg(xs, ys, weighting, no_intercept)
        built = True
    std_pts = list(zip(xs, ys))
    n_unk = max(1, min(6, int(p.get("n_unknowns") or 1)))
    reps_n = max(1, min(5, int(p.get("reps") or 3)))
    mw, units, unit_label = _resolve_units(comp, p)
    unknowns = []
    sum_found = 0.0
    sum_rec = 0.0
    worst_rsd = 0.0
    for i in range(n_unk):
        t_conc = conc_uM * (1.0 if n_unk == 1 else 0.7 + 0.6 * i / (n_unk - 1))
        rpts = [shot(t_conc) for _ in range(reps_n)]
        mean_a = round(sum(rpts) / len(rpts), 4)
        sd = math.sqrt(sum((r - mean_a) ** 2 for r in rpts) / max(1, reps_n - 1)) if reps_n > 1 else 0.0
        rsd = abs(sd / mean_a * 100) if mean_a else 999.0
        found = cal_inverse(cal, mean_a)
        rec = found / t_conc * 100 if t_conc else 0.0
        unknowns.append({
            "sample": f"UNK-{i + 1}", "conc_uM": round(t_conc, 3), "mean_abs": round(mean_a, 4),
            "rpts": [round(r, 4) for r in rpts], "sd": round(sd, 4), "rsd_pct": round(rsd, 3),
            "found_uM": round(found, 3), "recovery_pct": round(rec, 2),
            "found_val": convert_conc(found, units, mw), "found_unit": unit_label,
            "accepted": 98.0 <= rec <= 102.0 and rsd <= 2.0,
        })
        sum_found += found
        sum_rec += rec
        worst_rsd = max(worst_rsd, rsd)
    mean_found = sum_found / n_unk
    mean_rec = sum_rec / n_unk if n_unk else 0.0
    mean_a_ref = unknowns[0]["mean_abs"] if unknowns else 0.0
    analysis = {"found_uM": round(mean_found, 3), "recovery_pct": round(mean_rec, 2),
                "found_val": convert_conc(mean_found, units, mw), "units": unit_label,
                "rsd_pct": round(worst_rsd, 3), "r_squared": round(cal["r2"], 5),
                "slope": round(cal["coeffs"][1], 5),
                "intercept": round(cal["coeffs"][0], 5),
                "cal_type": cal["type"], "equation": cal["eq"], "sy_x": round(cal["syx"], 6),
                "lod_uM": round(cal["lod"], 3), "loq_uM": round(cal["loq"], 3),
                "weighting": cal.get("weighting", weighting),
                "no_intercept": bool(cal.get("no_intercept", no_intercept)),
                "meas_type": meas_type,
                "n_standards": cal["n"], "active_peak_nm": round(active_wl, 2),
                "n_peaks": len(peaks),
                "n_unknowns": n_unk, "reps": reps_n}
    checks = [
        {"name": "Linearity", "value": f"r2 = {analysis['r_squared']}", "limit": ">= 0.9990",
         "pass": cal["r2"] >= 0.9990},
        {"name": "Recovery", "value": f"{mean_rec:.2f} %", "limit": "98.0 - 102.0 %",
         "pass": 98.0 <= mean_rec <= 102.0},
        {"name": "Repeatability (RSD)", "value": f"{worst_rsd:.2f} %", "limit": "<= 2.00 %",
         "pass": worst_rsd <= 2.0},
        {"name": "Signal level", "value": f"{mean_a_ref:.3f} A", "limit": "0.100 - 2.500 A",
         "pass": 0.1 <= mean_a_ref <= 2.5},
    ]
    data = {"standards": std_rows, "replicates": [round(r, 4) for r in (unknowns[0]["rpts"] if unknowns else [])],
            "unknowns": unknowns, "peaks": peaks,
            "calibration": {"type": cal["type"], "eq": cal["eq"], "coeffs": cal["coeffs"],
                            "r2": round(cal["r2"], 5), "syx": round(cal["syx"], 6),
                            "lod": round(cal["lod"], 3), "loq": round(cal["loq"], 3), "n": cal["n"],
                            "weighting": cal.get("weighting", weighting),
                            "no_intercept": bool(cal.get("no_intercept", no_intercept)),
                            "meas_type": meas_type, "units": unit_label},
            "baseline": {"applied": bl_curve is not None,
                         "method": BASELINE_LABELS.get(bl_method, "none"), "pts": []}}
    cal_payload = None
    if built:
        cal_payload = {"instrument": p.get("instrument", ""), "compound": comp["name"],
                       "method_wl": active_wl, "cal_type": cal["type"], "coeffs": cal["coeffs"],
                       "equation": cal["eq"], "r2": cal["r2"], "syx": cal["syx"],
                       "lod": cal["lod"], "loq": cal["loq"], "standards": std_rows,
                       "weighting": cal.get("weighting", weighting),
                       "no_intercept": bool(cal.get("no_intercept", no_intercept)),
                       "meas_type": meas_type, "units": unit_label}
    return {"data": data, "analysis": analysis, "checks": checks,
            "chart": cal_chart(cal, std_pts, unknowns),
            "calibration": cal_payload, "active_wl": active_wl, "mean_a_ref": mean_a_ref,
            "summary": f"Found {mean_found:.2f} {unit_label}, recovery {mean_rec:.1f} %"}


def quant_preview(p):
    comp = compound(p.get("compound") or "Caffeine")
    inst = INSTRUMENTS.get(p.get("instrument") or "", INSTRUMENTS["UV-1900i"])
    rng = random.Random(20261008)
    conc = float(p.get("conc_uM") or default_conc(comp))
    p2 = dict(p)
    p2.pop("calibration", None)
    qc = quant_core(p2, comp, inst, {}, rng, "virtual", conc, conc,
                    float(p.get("path_cm") or 1.0), float(p.get("wl_start") or 200),
                    float(p.get("wl_end") or 800), float(p.get("step_nm") or 2),
                    p.get("speed") or "medium")
    return {"standards": qc["data"]["standards"], "unknowns": qc["data"]["unknowns"],
            "calibration": qc["data"]["calibration"], "baseline": qc["data"]["baseline"],
            "summary": qc["summary"], "active_peak_nm": qc["active_wl"],
            "n_peaks": qc["analysis"]["n_peaks"], "chart": qc["chart"]}


def reanalyze(data, analysis, params, comp, mode, wl):
    pts = data.get("points") or []
    wl = round(float(wl), 2)
    if not pts and not data.get("peaks"):
        return data, analysis, None
    a_at = min(pts, key=lambda q: abs(q[0] - wl))[1] if pts else None
    peaks = [dict(pk) for pk in (data.get("peaks") or [])]
    chosen = None
    if peaks:
        for pk in peaks:
            pk["active"] = False
        chosen = min(peaks, key=lambda pk: abs(pk["wl"] - wl))
        if abs(chosen["wl"] - wl) <= 2.0:
            chosen["active"] = True
        else:
            chosen = None
    analysis = dict(analysis)
    old_wl = float(analysis.get("active_peak_nm") or params.get("method_wl") or comp["method_wl"])
    e_old = eps_at(comp, old_wl)
    e_new = eps_at(comp, wl)
    ratio = (e_new / e_old) if e_old > 1e-9 else 1.0
    path = float(params.get("path_cm") or 1.0)
    analysis["active_peak_nm"] = wl
    if a_at is not None:
        analysis["abs_at_peak"] = round(a_at, 4)
        if e_new > 1e-9:
            analysis["conc_at_peak_uM"] = round(a_at / e_new / path * 1e6, 3)
    analysis["eps_ratio"] = round(ratio, 4)
    analysis["reanalyzed"] = True
    if chosen:
        analysis["peak_purity"] = chosen["purity"]
        analysis["peak_height_A"] = round(chosen["height_A"], 4)
        analysis["peak_area_A_nm"] = round(chosen["area_A_nm"], 3)
    data = dict(data)
    data["peaks"] = peaks
    chart = None
    if mode == "Quantitative":
        data["standards"] = [dict(s) for s in data.get("standards", [])]
        data["unknowns"] = [dict(u) for u in data.get("unknowns", [])]
        for s in data.get("standards", []):
            s["abs"] = round(s["abs"] * ratio, 4)
        for u in data.get("unknowns", []):
            u["mean_abs"] = round(u["mean_abs"] * ratio, 4)
            u["sd"] = round(u["sd"] * ratio, 4)
            u["rpts"] = [round(r * ratio, 4) for r in u.get("rpts", [])]
        cal_type = (data.get("calibration") or {}).get("type") or params.get("cal_type") or "linear"
        xs = [round(float(s["conc_uM"]), 2) for s in data.get("standards", [])]
        ys = [float(s["abs"]) for s in data.get("standards", [])]
        weighting = params.get("weighting") or "none"
        no_intercept = bool(params.get("no_intercept"))
        need = 5 if cal_type == "quadratic" else 3
        if len(xs) >= need:
            cal = quad_reg(xs, ys, weighting, no_intercept) if cal_type == "quadratic" \
                else lin_reg(xs, ys, weighting, no_intercept)
        else:
            old = data.get("calibration") or {}
            base = old.get("coeffs") or ([0.0, 1.0, 0.0] if cal_type == "quadratic" else [0.0, 1.0])
            cf = [round(c * ratio, 6) for c in base]
            cal = {"type": cal_type, "coeffs": cf, "eq": _eq_text(cal_type, cf, no_intercept),
                   "r2": float(old.get("r2", 0.0)), "syx": float(old.get("syx", 0.0)) * ratio,
                   "lod": float(old.get("lod", 0.0)), "loq": float(old.get("loq", 0.0)),
                   "weighting": weighting, "no_intercept": no_intercept, "n": len(xs)}
        mw, units, unit_label = _resolve_units(comp, params)
        sum_found = sum_rec = 0.0
        worst_rsd = 0.0
        for u in data.get("unknowns", []):
            found = cal_inverse(cal, u["mean_abs"])
            t_conc = float(u.get("conc_uM") or 0)
            rec = found / t_conc * 100 if t_conc else 0.0
            rsd = float(u.get("rsd_pct") or 0)
            u["found_uM"] = round(found, 3)
            u["found_val"] = convert_conc(found, units, mw)
            u["found_unit"] = unit_label
            u["recovery_pct"] = round(rec, 2)
            u["accepted"] = 98.0 <= rec <= 102.0 and rsd <= 2.0
            sum_found += found
            sum_rec += rec
            worst_rsd = max(worst_rsd, rsd)
        n_unk = len(data.get("unknowns", []))
        mean_found = sum_found / n_unk if n_unk else 0.0
        mean_rec = sum_rec / n_unk if n_unk else 0.0
        analysis.update({
            "found_uM": round(mean_found, 3), "found_val": convert_conc(mean_found, units, mw),
            "units": unit_label, "recovery_pct": round(mean_rec, 2),
            "rsd_pct": round(worst_rsd, 3), "r_squared": round(cal["r2"], 5),
            "slope": round(cal["coeffs"][1], 5), "intercept": round(cal["coeffs"][0], 5),
            "cal_type": cal["type"], "equation": cal["eq"], "sy_x": round(cal["syx"], 6),
            "lod_uM": round(cal["lod"], 3), "loq_uM": round(cal["loq"], 3),
            "active_peak_nm": wl,
        })
        if data.get("unknowns"):
            data["replicates"] = [round(r, 4) for r in data["unknowns"][0].get("rpts", [])]
            analysis["abs_at_peak"] = round(data["unknowns"][0]["mean_abs"], 4)
            analysis["conc_at_peak_uM"] = round(mean_found, 3)
        old_cal = data.get("calibration") or {}
        data["calibration"] = {"type": cal["type"], "eq": cal["eq"], "coeffs": cal["coeffs"],
                               "r2": round(cal["r2"], 5), "syx": round(cal["syx"], 6),
                               "lod": round(cal.get("lod", 0.0), 3), "loq": round(cal.get("loq", 0.0), 3),
                               "n": cal.get("n", len(xs)),
                               "weighting": cal.get("weighting", weighting),
                               "no_intercept": bool(cal.get("no_intercept", no_intercept)),
                               "meas_type": old_cal.get("meas_type", params.get("meas_type") or "height"),
                               "units": unit_label}
        chart = cal_chart(cal, list(zip(xs, ys)), data.get("unknowns", []))
        analysis["reanalyze_note"] = (f"Absorbances re-scaled from {old_wl:g} nm to {wl:g} nm "
                                      f"(epsilon ratio {ratio:.3f}); original judgment unchanged.")
    else:
        series = data.get("series")
        if series:
            new_series = []
            for s in series:
                s2 = dict(s)
                if s2.get("marker"):
                    s2["marker"] = (wl, f"{wl:.1f} nm")
                new_series.append(s2)
            data["series"] = new_series
            chart = line_chart(new_series, data.get("xlabel", "Wavelength (nm)"),
                               data.get("ylabel", "Absorbance (A)"))
        analysis["reanalyze_note"] = f"Active peak set to {wl:g} nm; identification and truth checks unchanged."
    return data, analysis, chart


def run_measurement(p, state, rng=None):
    rng = rng or random.Random()
    inst = INSTRUMENTS[p["instrument"]]
    comp = compound(p["compound"])
    mode = p["mode"]
    source = p.get("source", "virtual")
    conc_uM = float(p.get("conc_uM") or default_conc(comp))
    path = float(p.get("path_cm") or 1.0)
    wl0 = float(p.get("wl_start") or 200)
    wl1 = float(p.get("wl_end") or 800)
    step = float(p.get("step_nm") or 1.0)
    speed = p.get("speed", "medium")
    bw = float(p.get("bandwidth_nm") or 1.0)
    log = []
    actual_c, purity, pipet = truth_sample(comp, conc_uM, rng, source)

    def logstep(action, detail):
        prev = log[-1]["hash"] if log else None
        ts = rng.randint(0, 10 ** 9)
        h = hashlib.sha256(f"{prev}|{action}|{detail}|{ts}".encode()).hexdigest()
        log.append({"action": action, "detail": detail, "hash": h, "prev": prev})

    logstep("measurement.created", f"{mode} of {comp['name']} on {p['instrument']} ({source} source)")

    if mode == "Spectrum":
        true_pts = spectrum_points(comp, wl0, wl1, step, actual_c, path)
        if source == "physical":
            true_pts = [(x, y + 0.0004 * max(0.0, 600 - x) / 600.0) for x, y in true_pts]
        meas = []
        shifts = []
        scan_off = rng.gauss(0, inst["wl_accuracy"]) - float(state.get("wl_cal") or 0.0)
        for wl, a in true_pts:
            am, _sh = apply_instrument(wl, a, inst, state, rng, speed, source)
            meas.append((round(wl + scan_off, 3), round(am, 4)))
            shifts.append(scan_off)
        true_lambda, true_amax = peak_pick([(x, y) for x, y in true_pts])
        bl_method = p.get("baseline") or "none"
        baseline = None
        corrected = meas
        if bl_method in ("blank", "endpoint", "autozero"):
            baseline = baseline_curve(bl_method, meas, wl0, wl1, step, rng)
            corrected = subtract_baseline(meas, baseline)
        est_lambda, est_amax = peak_pick([(x, y) for x, y in corrected if wl0 <= x <= wl1])
        peaks = detect_peaks([(x, y) for x, y in corrected if wl0 <= x <= wl1],
                             threshold=float(p.get("peak_threshold") or 0.004),
                             min_span=float(p.get("min_peak_span") or 4.0), comp=comp)
        active_wl = resolve_active_peak(p, comp, peaks)
        peaks = mark_active(peaks, active_wl)
        best, score = None, -1.0
        for c2 in COMPOUNDS:
            lib = library_shape(c2, wl0, wl1, step)
            merged = [(x, y) for x, y in corrected]
            if len(lib) != len(merged):
                continue
            m = max(y for _, y in merged) or 1
            norm = [(x, y / m) for x, y in merged]
            num = sum(a * b for (_, a), (_, b) in zip(norm, lib))
            den = math.sqrt(sum(a * a for _, a in norm) * sum(b * b for _, b in lib)) or 1
            sc = num / den
            if sc > score:
                best, score = c2, sc
        truth = {
            "lambda_max_nm": true_lambda, "library_lambda_max_nm": comp["lambda_max"],
            "conc_uM": round(actual_c * 1e6, 3),
            "purity_pct": round(purity * 100, 2), "pipetting_error_pct": round(pipet * 100, 3),
            "abs_max": round(true_amax, 4),
        }
        analysis = {
            "lambda_max_nm": est_lambda, "abs_max": est_amax,
            "conc_uM": round(est_amax / max(comp["eps"], 1) / path * 1e6, 3),
            "identified_as": best["name"] if score > 0.90 else "no confident match",
            "match_score": round(score, 4),
            "wl_shift_mean_nm": round(sum(shifts) / len(shifts), 3),
            "active_peak_nm": active_wl, "n_peaks": len(peaks),
        }
        checks = [
            {"name": "Library match", "value": f"{analysis['identified_as']} ({analysis['match_score']})",
             "limit": "> 0.900", "pass": score > 0.90},
            {"name": "Absorbance range", "value": f"{est_amax:.3f} A", "limit": "0.100 - 2.500 A",
             "pass": 0.1 <= est_amax <= 2.5},
            {"name": "Wavelength vs truth", "value": f"{est_lambda:.1f} nm", "limit": f"± 1.0 nm of {true_lambda}",
             "pass": abs(est_lambda - true_lambda) <= 1.0},
        ]
        series = [
            {"label": "Baseline-corrected", "pts": corrected, "color": "#4cc2ff",
             "marker": (active_wl, f"{active_wl:.1f} nm")},
            {"label": "Library reference", "pts": [(x, y / (max(v for _, v in true_pts) or 1) * est_amax) for x, y in spectrum_points(comp, wl0, wl1, step, 1e-4, 1)],
             "color": "#ffc857", "dashed": True, "nodraw": False},
        ]
        if baseline is not None:
            series.append({"label": "Raw (uncorrected)", "pts": meas, "color": "#7d8796", "dashed": True})
            series.append({"label": BASELINE_LABELS.get(bl_method, "Baseline"), "pts": baseline,
                           "color": "#c77dff", "dashed": True})
        data = {"series": series, "xlabel": "Wavelength (nm)", "ylabel": "Absorbance (A)",
                "points": corrected, "truth_points": true_pts, "peaks": peaks,
                "baseline": {"applied": baseline is not None,
                             "method": BASELINE_LABELS.get(bl_method, "none"),
                             "pts": baseline or []}}
        return {"mode": mode, "data": data, "truth": truth, "analysis": analysis, "checks": checks,
                "chart": line_chart(series, "Wavelength (nm)", "Absorbance (A)"), "log": log,
                "summary": f"Lambda max {est_lambda:.1f} nm, {analysis['identified_as']}"}

    if mode == "Quantitative":
        qc = quant_core(p, comp, inst, state, rng, source, actual_c, conc_uM, path, wl0, wl1, step, speed)
        truth = {"conc_uM": round(actual_c * 1e6, 3), "purity_pct": round(purity * 100, 2),
                 "pipetting_error_pct": round(pipet * 100, 3),
                 "abs_true": round(qc["mean_a_ref"], 4),
                 "active_peak_nm": round(qc["active_wl"], 2)}
        return {"mode": mode, "data": qc["data"], "truth": truth, "analysis": qc["analysis"],
                "checks": qc["checks"], "chart": qc["chart"], "log": log,
                "summary": qc["summary"], "calibration": qc["calibration"]}

    if mode == "Photometric":
        wl = float(p.get("method_wl") or comp["method_wl"])
        n = int(p.get("readings") or 10)
        interval = float(p.get("interval_s") or 30)
        true_a = eps_at(comp, wl) * actual_c * path
        readings, t_list = [], []
        drift_true = 0.0
        for i in range(n):
            t = i * interval
            a_t = true_a + drift_true * (t / 600.0)
            a_m, _ = apply_instrument(wl, a_t, inst, state, rng, speed, source)
            if source == "physical" and i > n // 2:
                a_m += 0.0006 * (i - n // 2)
            readings.append(round(a_m, 4))
            t_list.append(t)
        mean = sum(readings) / n
        sd = math.sqrt(sum((r - mean) ** 2 for r in readings) / max(1, n - 1))
        rsd = abs(sd / mean * 100) if mean else 999.0
        mt = sum(t_list) / n
        s_tt = sum((t - mt) ** 2 for t in t_list)
        drift = (sum((t - mt) * (r - mean) for t, r in zip(t_list, readings)) / s_tt * 600.0) if s_tt else 0.0
        pred = [mean + (sum((t - mt) * (r - mean) for t, r in zip(t_list, readings)) / s_tt if s_tt else 0) * (t - mt) for t in t_list]
        sse = sum((r - p) ** 2 for r, p in zip(readings, pred))
        slope_se = math.sqrt((sse / max(1, n - 2)) / s_tt) if s_tt and n > 2 else 1.0
        drift_limit = 3 * slope_se * 600.0
        truth = {"abs_true": round(true_a, 4), "drift_A_per_10min": 0.0}
        analysis = {"mean_abs": round(mean, 4), "sd": round(sd, 4), "rsd_pct": round(rsd, 3),
                    "drift_A_per_10min": round(drift, 4), "readings": n}
        checks = [
            {"name": "Photometric stability (RSD)", "value": f"{rsd:.2f} %", "limit": "<= 1.00 %", "pass": rsd <= 1.0},
            {"name": "Baseline drift", "value": f"{drift:+.4f} A / 10 min", "limit": f"<= {drift_limit:.4f} (3 sigma)", "pass": abs(drift) <= drift_limit},
            {"name": "Signal level", "value": f"{mean:.3f} A", "limit": "0.100 - 2.500 A", "pass": 0.1 <= mean <= 2.5},
        ]
        data = {"readings": [{"t_s": t, "abs": r} for t, r in zip(t_list, readings)]}
        return {"mode": mode, "data": data, "truth": truth, "analysis": analysis, "checks": checks,
                "chart": line_chart([{"label": "A at method wavelength", "pts": list(zip(t_list, readings)), "color": "#4cc2ff"}],
                                    "Time (s)", "Absorbance (A)"),
                "log": log, "summary": f"Mean {mean:.4f} A, RSD {rsd:.2f} %"}

    t_end = float(p.get("t_end_min") or 30)
    interval = float(p.get("interval_s") or 15)
    wl = float(p.get("method_wl") or comp["method_wl"])
    k_true = round(rng.uniform(0.05, 0.16), 4)
    a0 = eps_at(comp, wl) * actual_c * path * 0.15
    ainf = eps_at(comp, wl) * actual_c * path
    t_pts, a_pts = [], []
    t = 0.0
    while t <= t_end * 60 + 1e-9:
        a_t = ainf - (ainf - a0) * math.exp(-k_true * t / 60.0)
        a_m, _ = apply_instrument(wl, a_t, inst, state, rng, speed, source)
        t_pts.append(round(t, 1))
        a_pts.append(round(a_m, 4))
        t += interval
    best_fit = None
    s = 1.001
    a0e = a_pts[0]
    while s <= 2.20:
        a_inf_est = max(a_pts) * s
        xs2, ys2 = [], []
        for tt, aa in zip(t_pts, a_pts):
            d = a_inf_est - aa
            if tt > 0 and d > 0.01 * max(a_inf_est - a0e, 1e-9):
                xs2.append(tt / 60.0)
                ys2.append(math.log(d))
        if len(xs2) > 3:
            mx, my = sum(xs2) / len(xs2), sum(ys2) / len(ys2)
            sxx = sum((x - mx) ** 2 for x in xs2)
            if sxx:
                kcand = -sum((x - mx) * (y - my) for x, y in zip(xs2, ys2)) / sxx
                if kcand > 0:
                    sse = 0.0
                    for tt, aa in zip(t_pts, a_pts):
                        pred = a_inf_est - (a_inf_est - a0e) * math.exp(-kcand * tt / 60.0)
                        sse += (aa - pred) ** 2
                    if best_fit is None or sse < best_fit[2]:
                        best_fit = (a_inf_est, kcand, sse)
        s += 0.002
    if best_fit:
        a_inf_est, k_fit, sse = best_fit
        mean_a = sum(a_pts) / len(a_pts)
        sst = sum((a - mean_a) ** 2 for a in a_pts) or 1e-12
        r2 = max(0.0, 1 - sse / sst)
    else:
        a_inf_est, k_fit, r2 = max(a_pts) * 1.02, 0.0, 0.0
    half_life = math.log(2) / k_fit if k_fit > 0 else 0.0
    truth = {"k_true_per_min": k_true, "half_life_min": round(math.log(2) / k_true, 2),
             "a0": round(a0, 4), "a_inf": round(ainf, 4)}
    analysis = {"k_fit_per_min": round(k_fit, 4), "half_life_min": round(half_life, 2),
                "r_squared": round(r2, 5), "a_inf_est": round(a_inf_est, 4)}
    err_pct = abs(k_fit - k_true) / k_true * 100 if k_true else 0.0
    checks = [
        {"name": "First-order fit", "value": f"r2 = {analysis['r_squared']}", "limit": ">= 0.9950", "pass": r2 >= 0.995},
        {"name": "Rate constant", "value": f"{k_fit:.4f} /min", "limit": f"true {k_true:.4f} (virtual)", "pass": err_pct <= 5.0},
        {"name": "Half-life", "value": f"{half_life:.2f} min", "limit": "reportable", "pass": half_life > 0},
    ]
    data = {"kinetic": [{"t_s": tt, "abs": aa} for tt, aa in zip(t_pts, a_pts)]}
    return {"mode": mode, "data": data, "truth": truth, "analysis": analysis, "checks": checks,
            "chart": line_chart([{"label": "Reaction progress", "pts": list(zip(t_pts, a_pts)), "color": "#4cc2ff"}],
                                "Time (s)", "Absorbance (A)"),
            "log": log, "summary": f"k = {k_fit:.4f} /min, t½ = {half_life:.2f} min"}


METRICS = {
    "Spectrum": [("wavelength_nm", "Wavelength accuracy", lambda r: abs(r["analysis"]["lambda_max_nm"] - r["truth"]["lambda_max_nm"]))],
    "Quantitative": [("recovery_pct", "Assay recovery", lambda r: abs(r["analysis"]["recovery_pct"] - 100.0))],
    "Photometric": [("rsd_pct", "Photometric repeatability", lambda r: r["analysis"]["rsd_pct"])],
    "Time course": [("kinetic_pct", "Kinetic rate accuracy", lambda r: abs(r["analysis"]["k_fit_per_min"] - r["truth"]["k_true_per_min"]) / max(r["truth"]["k_true_per_min"], 1e-9) * 100.0)],
}

CAUSES = {
    "wavelength_nm": ("peak-picking bias on overlapping bands at the configured bandwidth",
                      "bandwidth-aware sub-pixel peak interpolation re-weighted"),
    "recovery_pct": ("stray-light contribution not fully modelled above 2 A on this instrument",
                     "instrument stray-light term re-fitted and calibration re-anchored"),
    "rsd_pct": ("lamp flicker under-represented in the noise model at this scan speed",
                "noise model scaled to observed repeatability"),
    "kinetic_pct": ("end-point (A-infinity) estimate biased in the first-order fit",
                    "late-point weighting applied to the linearised fit"),
}
