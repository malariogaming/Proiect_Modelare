"""
Battle Simulator (Ursina) - ERA MODERNA

Controale:
  1 / 2 / 3 / 4 / 5   alege unitatea (Soldat / Lunetist / RPG / Mitralior / Tanc)
  T             schimba echipa
  Click stanga  plaseaza unitatea (tine apasat + misca mouse-ul = "pictezi" unitati)
  Z             sterge ultima unitate plasata
  SPACE         porneste lupta
  R             reset
  Click dreapta + mouse = roteste camera | Scroll = zoom | Click mijloc = muta camera

Unitati:
  SOLDAT     pusca de asalt; echilibrat, incarcator de 12 gloante
  LUNETIST   bataie aproape cat toata arena, damage mare, dar trage rar si e slab de aproape
  RPG        racheta lenta cu explozie (damage pe zona); de 3x mai eficienta contra tancurilor
  MITRALIOR  foc continuu si imprecis, multa viata; reincarca dupa 40 de gloante
  TANC       blindat (gloantele il zgarie abia), obuz exploziv, greu de oprit, se roteste incet

Fisiere audio optionale (langa script):
  pusca.wav, sniper.wav, rpg.wav, mitraliera.wav, tun.wav, explozie.wav, muzica.mp3
Daca lipsesc, jocul ruleaza fara sunet.
"""
from ursina import *
from panda3d.core import NodePath, Point2, Point3, TransparencyAttrib, loadPrcFileData
from pathlib import Path
import math
import random
import time as pytime  # 'time' din ursina contine time.dt, deci folosim alt alias

loadPrcFileData('', 'transform-cache false')
app = Ursina(development_mode=False)
window.title = 'Battle Simulator - Era Moderna'
window.fps_counter.enabled = True
window.color = color.hsv(205, 0.25, 0.92)

# ---------------------------------------------------------------- CONSTANTE
ARENA_HALF = 19             # zona de lupta (unitatile nu ies din ea)
WORLD_HALF = 34             # tot terenul, inclusiv muntii din jur
TERRAIN_CELL = 1.0          # rezolutia terenului
CELL_SIZE = 2.0             # celula grilei spatiale (unitatile mari cauta pe 2 celule in jur)
BASE_RADIUS = 0.5           # raza unui soldat
MAX_UNIT_RADIUS = 1.4       # raza tancului (cea mai mare unitate)
SEPARATION_STRENGTH = 4     # cat de tare se imping unitatile intre ele
TURN_SPEED = 10             # viteza de rotire spre inamic
RECOIL_TIME = 0.12          # durata reculului armei
AIM_TOLERANCE = 15          # trage doar daca e intors spre tinta (grade)
DEATH_DELAY = 1.5           # dupa cat timp dispare cadavrul
WRECK_DELAY = 4.0           # cat ramane epava unui tanc
WATER_Y = -0.9              # nivelul apei din rau
WATER_SLOWDOWN = 0.55       # prin apa se merge mai incet
MAX_DT = 1 / 20             # evita "teleportarile" cand un frame dureaza mult
MAX_EFFECTS = 350           # limita de fum/praf simultan (exploziile trec oricum)

TEAM_NAMES = {'red': 'ROSIE', 'blue': 'ALBASTRA'}
FOG_COLOR = color.hsv(205, 0.18, 0.9)


def rgb(r, g, b, a=1.0):
    """Culori 0-1, independent de versiunea Ursina (color.rgb s-a schimbat intre versiuni)."""
    return Color(r, g, b, a)


def mix(a, b, t):
    return Color(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t, 1)


TEAM_COLORS = {'red': rgb(0.80, 0.16, 0.14), 'blue': rgb(0.16, 0.36, 0.85)}
TEAM_DARK = {'red': rgb(0.50, 0.09, 0.08), 'blue': rgb(0.09, 0.19, 0.48)}
TEAM_UI = {'red': color.red, 'blue': color.azure}

SKIN = rgb(0.96, 0.76, 0.60)
BLACK = rgb(0.08, 0.08, 0.08)
WOOD = rgb(0.55, 0.36, 0.18)
CLOTH_WHITE = rgb(0.92, 0.90, 0.85)
OLIVE = rgb(0.34, 0.38, 0.22)
DARK_OLIVE = rgb(0.22, 0.25, 0.14)
KHAKI = rgb(0.64, 0.57, 0.40)
WEBBING = rgb(0.17, 0.18, 0.13)
GUNMETAL = rgb(0.24, 0.25, 0.27)
GUN_BLACK = rgb(0.09, 0.09, 0.10)
POLYMER = rgb(0.30, 0.28, 0.24)
BRASS = rgb(0.85, 0.65, 0.25)
ROCKET_GREEN = rgb(0.40, 0.44, 0.30)
GHILLIE = (rgb(0.30, 0.36, 0.17), rgb(0.40, 0.38, 0.22), rgb(0.24, 0.30, 0.14), rgb(0.45, 0.42, 0.28))


def clamp_arena(value):
    return max(-ARENA_HALF, min(ARENA_HALF, value))


# ================================================================ MESH BUILDER
# Construim geometria low-poly direct (triunghiuri + culori pe varfuri).
# Lumina este "coapta": fiecare fata primeste o nuanta dupa cat de mult
# priveste spre soare, deci obtinem aspect 3D fara shader de lumini.
SUN = Vec3(0.45, 0.85, -0.35).normalized()


def _rot(v, rx, ry, rz):
    x, y, z = v
    if rx:
        a = math.radians(rx); c, s = math.cos(a), math.sin(a)
        y, z = y * c - z * s, y * s + z * c
    if ry:
        a = math.radians(ry); c, s = math.cos(a), math.sin(a)
        x, z = x * c + z * s, -x * s + z * c
    if rz:
        a = math.radians(rz); c, s = math.cos(a), math.sin(a)
        x, y = x * c - y * s, x * s + y * c
    return (x, y, z)


class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.colors = []

    def tri(self, a, b, c, col, outward=None, shade=True):
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        if outward is not None and nx * outward[0] + ny * outward[1] + nz * outward[2] < 0:
            b, c = c, b
            nx, ny, nz = -nx, -ny, -nz
        if shade:
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1
            d = max(0.0, (nx * SUN.x + ny * SUN.y + nz * SUN.z) / ln)
            k = 0.58 + 0.52 * d
            col = Color(min(1, col[0] * k), min(1, col[1] * k), min(1, col[2] * k), col[3])
        # Ursina foloseste un sistem de coordonate "left-handed": ordinea inversa = fata vizibila
        self.verts += (a, c, b)
        self.colors += (col, col, col)

    def quad(self, a, b, c, d, col, outward=None, shade=True):
        self.tri(a, b, c, col, outward, shade)
        self.tri(a, c, d, col, outward, shade)

    def box(self, center, size, col, rot=(0, 0, 0), jitter=0.0, rng=None, shade=True):
        cx, cy, cz = center
        hx, hy, hz = size[0] / 2, size[1] / 2, size[2] / 2
        corners = []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    p = (sx * hx, sy * hy, sz * hz)
                    if jitter:
                        p = (p[0] * (1 + rng.uniform(-jitter, jitter)),
                             p[1] * (1 + rng.uniform(-jitter, jitter)),
                             p[2] * (1 + rng.uniform(-jitter, jitter)))
                    p = _rot(p, *rot)
                    corners.append((cx + p[0], cy + p[1], cz + p[2]))

        def C(sx, sy, sz):
            return corners[((sx > 0) << 2) | ((sy > 0) << 1) | (sz > 0)]

        faces = [
            ((1, -1, -1), (1, 1, -1), (1, 1, 1), (1, -1, 1)),
            ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1)),
            ((-1, 1, -1), (-1, 1, 1), (1, 1, 1), (1, 1, -1)),
            ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1)),
            ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)),
            ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1)),
        ]
        for f in faces:
            pts = [C(*p) for p in f]
            fc = [sum(p[i] for p in pts) / 4 for i in range(3)]
            self.quad(*pts, col, outward=(fc[0] - cx, fc[1] - cy, fc[2] - cz), shade=shade)

    def limb(self, p0, p1, thick, col):
        """Bara (brat, antebrat) intre doua puncte; rotatia se calculeaza automat."""
        dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 0.001
        pitch = -math.degrees(math.asin(max(-1.0, min(1.0, dy / length))))
        yaw = math.degrees(math.atan2(dx, dz))
        center = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, (p0[2] + p1[2]) / 2)
        self.box(center, (thick, thick, length + thick * 0.5), col, rot=(pitch, yaw, 0))

    def blob(self, center, radius, col, sides=8, shade=True):
        """'Sfera' low-poly (doua inele + doi poli) - pentru explozii, fum, praf."""
        cx, cy, cz = center
        top, bot = (cx, cy + radius, cz), (cx, cy - radius, cz)
        angs = [i * 2 * math.pi / sides for i in range(sides)]
        up = [(cx + math.cos(a) * radius * 0.87, cy + 0.5 * radius, cz + math.sin(a) * radius * 0.87) for a in angs]
        dn = [(cx + math.cos(a) * radius * 0.87, cy - 0.5 * radius, cz + math.sin(a) * radius * 0.87) for a in angs]

        def out(*pts):
            return (sum(p[0] for p in pts) / len(pts) - cx, sum(p[1] for p in pts) / len(pts) - cy,
                    sum(p[2] for p in pts) / len(pts) - cz)

        for i in range(sides):
            j = (i + 1) % sides
            self.tri(up[i], up[j], top, col, outward=out(up[i], up[j], top), shade=shade)
            self.quad(dn[i], dn[j], up[j], up[i], col, outward=out(dn[i], dn[j], up[j], up[i]), shade=shade)
            self.tri(dn[j], dn[i], bot, col, outward=out(dn[i], dn[j], bot), shade=shade)

    def cone(self, base, radius, height, col, sides=6, top_radius=0.0, rot0=0.0, cap=True):
        """Con / trunchi de con / cilindru low-poly, vertical."""
        bx, by, bz = base
        ring_b, ring_t = [], []
        for i in range(sides):
            a = rot0 + i * 2 * math.pi / sides
            ca, sa = math.cos(a), math.sin(a)
            ring_b.append((bx + ca * radius, by, bz + sa * radius))
            ring_t.append((bx + ca * top_radius, by + height, bz + sa * top_radius))
        for i in range(sides):
            j = (i + 1) % sides
            mid = (math.cos(rot0 + (i + 0.5) * 2 * math.pi / sides), 0.3, math.sin(rot0 + (i + 0.5) * 2 * math.pi / sides))
            if top_radius > 0:
                self.quad(ring_b[i], ring_b[j], ring_t[j], ring_t[i], col, outward=mid)
            else:
                self.tri(ring_b[i], ring_b[j], (bx, by + height, bz), col, outward=mid)
        if cap:
            for i in range(sides):
                j = (i + 1) % sides
                self.tri((bx, by, bz), ring_b[j], ring_b[i], col, outward=(0, -1, 0))
                if top_radius > 0:
                    self.tri((bx, by + height, bz), ring_t[i], ring_t[j], col, outward=(0, 1, 0))

    def disc(self, center, radius, col, sides=10, shade=False):
        cx, cy, cz = center
        for i in range(sides):
            a0, a1 = i * 2 * math.pi / sides, (i + 1) * 2 * math.pi / sides
            self.tri((cx, cy, cz), (cx + math.cos(a0) * radius, cy, cz + math.sin(a0) * radius),
                     (cx + math.cos(a1) * radius, cy, cz + math.sin(a1) * radius), col, outward=(0, 1, 0), shade=shade)

    def ring(self, center, r_in, r_out, col, sides=24):
        cx, cy, cz = center
        for i in range(sides):
            a0, a1 = i * 2 * math.pi / sides, (i + 1) * 2 * math.pi / sides
            p = [(cx + math.cos(a) * r, cy, cz + math.sin(a) * r) for a, r in ((a0, r_in), (a0, r_out), (a1, r_out), (a1, r_in))]
            self.quad(*p, col, outward=(0, 1, 0), shade=False)

    def build(self):
        return Mesh(vertices=self.verts, triangles=list(range(len(self.verts))),
                    colors=self.colors, static=True)


def attach_mesh(parent, mesh, name='part'):
    """Copie a unui mesh partajat (Panda3D refoloseste geometria)."""
    node = parent.attachNewNode(name)
    mesh.copyTo(node)
    return node


def apply_fog(entity):
    entity.set_shader_input('fog_color', FOG_COLOR)
    entity.set_shader_input('fog_start', 0)
    entity.set_shader_input('fog_end', 260)


# ================================================================ TEREN
def river_center(x):
    return 2.5 * math.sin(x * 0.16 + 0.6) + 1.2 * math.sin(x * 0.41)


def road_center(z):
    return 5.0 * math.sin(z * 0.11 + 1.0) + 2.0


def terrain_height_raw(x, z):
    h = (0.9 * math.sin(x * 0.21 + 1.0) * math.cos(z * 0.17 - 0.5)
         + 0.5 * math.sin(x * 0.09 - z * 0.13 + 2.0)
         + 0.25 * math.sin(x * 0.5 + z * 0.37))
   
    d = z - river_center(x)
    w = math.exp(-(d * d) / 5.0)
    h = h * (1 - w) + (WATER_Y - 0.45) * w
    
    edge = (abs(x) ** 6 + abs(z) ** 6) ** (1 / 6) - ARENA_HALF - 1.5
    if edge > 0:
        edge = min(edge, 10)
        h += edge * edge * 0.11 * (1 + 0.45 * math.sin(x * 0.45 + z * 0.3) + 0.25 * math.sin(x * 1.1 - z * 0.9))
    return h


class Terrain:
    def __init__(self):
        n = int(2 * WORLD_HALF / TERRAIN_CELL)
        self.n = n
        self.origin = -WORLD_HALF
        self.h = [[terrain_height_raw(self.origin + i * TERRAIN_CELL, self.origin + j * TERRAIN_CELL)
                   for j in range(n + 1)] for i in range(n + 1)]

    def height_at(self, x, z):
        """Interpolare exact pe aceleasi triunghiuri ca mesh-ul (unitatile stau pe sol)."""
        fx = (x - self.origin) / TERRAIN_CELL
        fz = (z - self.origin) / TERRAIN_CELL
        i = min(max(int(fx), 0), self.n - 1)
        j = min(max(int(fz), 0), self.n - 1)
        fx -= i
        fz -= j
        hi, hi1 = self.h[i], self.h[i + 1]
        ha, hb, hc, hd = hi[j], hi1[j], hi1[j + 1], hi[j + 1]
        if fx >= fz:
            return ha + fx * (hb - ha) + fz * (hc - hb)
        return ha + fz * (hd - ha) + fx * (hc - hd)

    def build_mesh(self):
        rng = random.Random(3)
        mb = MeshBuilder()
        c = TERRAIN_CELL
        for i in range(self.n):
            for j in range(self.n):
                x0, z0 = self.origin + i * c, self.origin + j * c
                a = (x0, self.h[i][j], z0)
                b = (x0 + c, self.h[i + 1][j], z0)
                cc = (x0 + c, self.h[i + 1][j + 1], z0 + c)
                d = (x0, self.h[i][j + 1], z0 + c)
                for tri in ((a, b, cc), (a, cc, d)):
                    mb.tri(*tri, self.ground_color(tri, rng), outward=(0, 1, 0))
        return mb.build()

    @staticmethod
    def ground_color(tri, rng):
        x = sum(p[0] for p in tri) / 3
        y = sum(p[1] for p in tri) / 3
        z = sum(p[2] for p in tri) / 3
        ys = [p[1] for p in tri]
        slope = max(ys) - min(ys)
        n = rng.uniform(-0.035, 0.035)
        inside = abs(x) < ARENA_HALF + 1 and abs(z) < ARENA_HALF + 1

        if y < WATER_Y + 0.12:
            return rgb(0.62 + n, 0.55 + n, 0.38 + n)                     # nisip / albie
        if y > 11:
            return rgb(0.93 + n, 0.94 + n, 0.97 + n)                     # zapada
        if y > 4.5 or slope > 2.2:
            return rgb(0.47 + n, 0.45 + n, 0.43 + n)                     # stanca
        if inside and abs(x - road_center(z)) < 1.1:
            return rgb(0.60 + n, 0.47 + n, 0.30 + n)                     # drum de pamant
        if y < WATER_Y + 0.45:
            return rgb(0.40 + n, 0.55 + n, 0.25 + n)                     # mal
        t = max(0, min(1, (y + 1) / 4))
        patch = 0.04 * math.sin(x * 0.7) * math.cos(z * 0.6)
        return rgb(0.30 + 0.12 * t + n + patch, 0.55 + 0.10 * t + n + patch, 0.22 + n)


terrain = Terrain()


# ================================================================ DECOR (un singur mesh)
OBSTACLES = []      # (x, z, raza) - piedici solide in arena
OBSTACLE_GRID = {}


def add_obstacle(x, z, r):
    OBSTACLES.append((x, z, r))
    reach = r + MAX_UNIT_RADIUS + 1.0
    for i in range(int((x - reach) // CELL_SIZE), int((x + reach) // CELL_SIZE) + 1):
        for j in range(int((z - reach) // CELL_SIZE), int((z + reach) // CELL_SIZE) + 1):
            OBSTACLE_GRID.setdefault((i, j), []).append((x, z, r))


def build_pine(mb, x, z, s, rng):
    y = terrain.height_at(x, z)
    mb.cone((x, y - 0.2, z), 0.18 * s, 0.9 * s, WOOD, sides=5, top_radius=0.12 * s)
    g = rgb(0.13 + rng.uniform(0, 0.05), 0.36 + rng.uniform(0, 0.08), 0.18)
    for k, (r, h, off) in enumerate(((1.1, 1.4, 0.6), (0.85, 1.2, 1.3), (0.55, 1.0, 1.95))):
        mb.cone((x, y + off * s, z), r * s, h * s, g if k != 1 else rgb(g[0] * 1.1, g[1] * 1.1, g[2]),
                sides=7, rot0=rng.uniform(0, 3))


def build_oak(mb, x, z, s, rng):
    y = terrain.height_at(x, z)
    mb.cone((x, y - 0.2, z), 0.22 * s, 1.4 * s, WOOD, sides=5, top_radius=0.15 * s)
    for _ in range(4):
        g = rgb(0.25 + rng.uniform(0, 0.08), 0.48 + rng.uniform(0, 0.1), 0.16)
        mb.box((x + rng.uniform(-0.5, 0.5) * s, y + (1.6 + rng.uniform(0, 0.7)) * s, z + rng.uniform(-0.5, 0.5) * s),
               (1.1 * s, 0.9 * s, 1.1 * s), g, rot=(rng.uniform(-15, 15), rng.uniform(0, 90), 0), jitter=0.2, rng=rng)


def build_rock(mb, x, z, s, rng):
    y = terrain.height_at(x, z)
    gray = 0.45 + rng.uniform(-0.06, 0.08)
    mb.box((x, y + 0.25 * s, z), (1.4 * s, 0.9 * s, 1.2 * s), rgb(gray, gray * 0.98, gray * 0.95),
           rot=(rng.uniform(-10, 10), rng.uniform(0, 90), rng.uniform(-10, 10)), jitter=0.3, rng=rng)
    if rng.random() < 0.6:
        mb.box((x + 0.5 * s, y + 0.1 * s, z + 0.4 * s), (0.6 * s, 0.4 * s, 0.6 * s), rgb(gray * 0.9, gray * 0.9, gray * 0.88),
               rot=(0, rng.uniform(0, 90), 0), jitter=0.3, rng=rng)


def build_world():
    rng = random.Random(42)
    mb = MeshBuilder()

    def in_river(x, z, margin=2.2):
        return abs(z - river_center(x)) < margin

    def on_road(x, z):
        return abs(x - road_center(z)) < 1.8

    # Padure pe dealurile din jurul arenei (doar decor)
    placed = 0
    while placed < 150:
        x, z = rng.uniform(-WORLD_HALF + 1, WORLD_HALF - 1), rng.uniform(-WORLD_HALF + 1, WORLD_HALF - 1)
        edge = max(abs(x), abs(z)) - ARENA_HALF
        if edge < 1.5 or terrain.height_at(x, z) > 9 or in_river(x, z, 1.5):
            continue
        (build_pine if rng.random() < 0.7 else build_oak)(mb, x, z, rng.uniform(0.9, 1.5), rng)
        placed += 1

    # Cativa copaci si bolovani IN arena: piedici reale, ocolite de unitati
    placed = 0
    while placed < 14:
        x, z = rng.uniform(-ARENA_HALF + 2, ARENA_HALF - 2), rng.uniform(-ARENA_HALF + 2, ARENA_HALF - 2)
        if in_river(x, z) or on_road(x, z) or any(math.hypot(x - ox, z - oz) < 5 for ox, oz, _ in OBSTACLES):
            continue
        s = rng.uniform(0.8, 1.3)
        if placed % 2:
            build_rock(mb, x, z, s, rng)
            add_obstacle(x, z, 0.75 * s)
        else:
            (build_pine if rng.random() < 0.5 else build_oak)(mb, x, z, s, rng)
            add_obstacle(x, z, 0.35 * s)
        placed += 1

    # Smocuri de iarba, tufe si flori (fara coliziune)
    for _ in range(260):
        x, z = rng.uniform(-WORLD_HALF + 2, WORLD_HALF - 2), rng.uniform(-WORLD_HALF + 2, WORLD_HALF - 2)
        y = terrain.height_at(x, z)
        if y < WATER_Y + 0.25 or y > 5 or on_road(x, z):
            continue
        r = rng.random()
        if r < 0.55:
            g = rgb(0.30, 0.58 + rng.uniform(0, 0.1), 0.20)
            for k in range(3):
                mb.cone((x + rng.uniform(-0.15, 0.15), y - 0.05, z + rng.uniform(-0.15, 0.15)),
                        0.07, rng.uniform(0.3, 0.5), g, sides=3, rot0=rng.uniform(0, 3), cap=False)
        elif r < 0.8:
            mb.box((x, y + 0.15, z), (0.7, 0.5, 0.7), rgb(0.22, 0.45, 0.16), rot=(0, rng.uniform(0, 90), 0), jitter=0.25, rng=rng)
        else:
            fc = rng.choice((rgb(0.95, 0.9, 0.3), rgb(0.95, 0.95, 0.95), rgb(0.85, 0.35, 0.6), rgb(0.6, 0.5, 0.95)))
            for k in range(4):
                fx, fz = x + rng.uniform(-0.4, 0.4), z + rng.uniform(-0.4, 0.4)
                mb.box((fx, terrain.height_at(fx, fz) + 0.12, fz), (0.12, 0.12, 0.12), fc)

    # Pietre in rau (doar decor)
    for k in range(12):
        x = rng.uniform(-ARENA_HALF, ARENA_HALF)
        z = river_center(x) + rng.uniform(-1, 1)
        build_rock(mb, x, z, rng.uniform(0.25, 0.45), rng)

    return mb.build()


ground = Entity(model=terrain.build_mesh())
decor = Entity(model=build_world())
water = Entity(model='plane', scale=(2 * WORLD_HALF, 1, 2 * WORLD_HALF), y=WATER_Y,
               color=rgb(0.25, 0.55, 0.85, 0.65))
water.setTransparency(TransparencyAttrib.MAlpha)
water.setDepthWrite(False)
for e in (ground, decor, water):
    apply_fog(e)


# ================================================================ MODELE UNITATI
# Fiecare model se construieste O SINGURA DATA per (tip, echipa) si se refoloseste.
# Un soldat are: corp (static), 2 picioare (animate la mers) si un "rig" = ambele brate
# + arma, rotit dintr-un singur pivot (umeri) ca sa tinteasca, sa coboare arma sau sa faca recul.
_model_cache = {}


def cached(key, factory):
    if key not in _model_cache:
        _model_cache[key] = factory()
    return _model_cache[key]


def leg_mesh(trouser, boot):
    mb = MeshBuilder()
    mb.box((0, -0.32, 0), (0.18, 0.64, 0.2), trouser)
    mb.box((0, -0.64, 0.04), (0.2, 0.12, 0.28), boot)
    return mb.build()


def soldier_body(mb, team, headgear='helmet'):
    T = TEAM_COLORS[team]
    mb.box((0, 0.30, 0), (0.48, 0.60, 0.30), T)                          # bluza in culoarea echipei
    mb.box((0, 0.37, 0), (0.52, 0.38, 0.34), OLIVE)                      # vesta tactica
    for px in (-0.14, 0.0, 0.14):
        mb.box((px, 0.27, 0.18), (0.11, 0.15, 0.05), DARK_OLIVE)         # port-incarcatoare
    mb.box((0.13, 0.47, 0.175), (0.13, 0.06, 0.02), T)                   # ecuson
    mb.box((0, 0.06, 0), (0.52, 0.08, 0.33), WEBBING)                    # centura
    mb.box((0, 0.64, 0), (0.16, 0.08, 0.16), SKIN)                       # gat
    mb.box((0, 0.84, 0), (0.34, 0.36, 0.34), SKIN)                       # cap
    mb.box((-0.08, 0.85, 0.171), (0.06, 0.06, 0.01), BLACK)              # ochi
    mb.box((0.08, 0.85, 0.171), (0.06, 0.06, 0.01), BLACK)
    if headgear == 'helmet':
        mb.box((0, 1.01, -0.01), (0.42, 0.20, 0.42), OLIVE)              # casca
        mb.box((0, 0.925, -0.01), (0.46, 0.04, 0.46), DARK_OLIVE)        # bordura castii
        mb.box((0, 0.99, -0.01), (0.43, 0.06, 0.43), T)                  # banda echipei
        mb.box((0, 1.04, 0.205), (0.16, 0.07, 0.04), GUN_BLACK)          # suport ochelari de noapte
    elif headgear == 'boonie':
        mb.box((0, 1.05, 0), (0.38, 0.12, 0.38), KHAKI)                  # palarie de camuflaj
        mb.box((0, 1.02, 0), (0.39, 0.04, 0.39), T)
        mb.box((0, 0.99, 0), (0.64, 0.03, 0.64), KHAKI)                  # boruri


def add_arms(mb, sleeve, r_elbow, r_hand, l_elbow, l_hand):
    """Brate in pozitie de tinere a armei; coordonate relative la pivotul umerilor."""
    for shoulder, elbow, hand in (((0.31, 0.0, 0.0), r_elbow, r_hand), ((-0.31, 0.0, 0.0), l_elbow, l_hand)):
        mb.box(shoulder, (0.2, 0.17, 0.2), sleeve)                       # umar
        mb.limb(shoulder, elbow, 0.15, sleeve)                           # brat
        mb.limb(elbow, hand, 0.13, sleeve)                               # antebrat
        mb.box(hand, (0.12, 0.12, 0.12), SKIN)                           # mana


def assault_rifle(mb, x=0.10):
    mb.box((x, -0.11, -0.04), (0.07, 0.13, 0.26), POLYMER)              # pat
    mb.box((x, -0.07, 0.28), (0.08, 0.12, 0.40), GUNMETAL)              # corp
    mb.box((x, -0.21, 0.38), (0.06, 0.20, 0.10), GUN_BLACK, rot=(-15, 0, 0))   # incarcator
    mb.box((x, -0.18, 0.18), (0.05, 0.13, 0.06), GUN_BLACK)             # maner
    mb.box((x, -0.06, 0.62), (0.08, 0.09, 0.28), POLYMER)               # garda
    mb.box((x, -0.05, 0.88), (0.035, 0.035, 0.26), GUN_BLACK)           # teava
    mb.box((x, 0.01, 0.28), (0.05, 0.05, 0.14), GUN_BLACK)              # dispozitiv de ochire


def sniper_rifle(mb, x=0.10):
    mb.box((x, -0.11, -0.06), (0.07, 0.16, 0.30), DARK_OLIVE)           # pat
    mb.box((x, -0.07, 0.32), (0.08, 0.11, 0.50), DARK_OLIVE)            # corp
    mb.box((x, -0.18, 0.16), (0.05, 0.13, 0.06), GUN_BLACK)             # maner
    mb.box((x, -0.16, 0.36), (0.06, 0.09, 0.10), GUN_BLACK)             # incarcator
    mb.box((x, -0.05, 1.02), (0.04, 0.04, 0.82), GUN_BLACK)             # teava lunga
    mb.box((x, -0.05, 1.42), (0.07, 0.07, 0.08), GUN_BLACK)             # frana de gura
    mb.box((x, 0.05, 0.32), (0.06, 0.06, 0.36), GUN_BLACK)              # luneta
    mb.box((x, 0.05, 0.52), (0.085, 0.085, 0.07), GUN_BLACK)
    mb.box((x, 0.05, 0.12), (0.075, 0.075, 0.06), GUN_BLACK)
    mb.box((x, 0.05, 0.557), (0.06, 0.06, 0.005), rgb(0.35, 0.75, 1.0), shade=False)   # lentila
    mb.box((x, -0.005, 0.32), (0.03, 0.05, 0.05), GUN_BLACK)            # prindere luneta
    for dx in (-0.03, 0.03):
        mb.box((x + dx, -0.12, 0.92), (0.02, 0.02, 0.30), GUN_BLACK)    # bipied pliat


def rpg_launcher(mb, x=0.22, y=0.10):
    mb.box((x, y, 0.10), (0.12, 0.12, 1.10), OLIVE)                     # tub
    mb.box((x, y, -0.47), (0.17, 0.17, 0.08), DARK_OLIVE)               # palnia din spate
    mb.box((x, y, 0.62), (0.15, 0.15, 0.06), DARK_OLIVE)
    mb.box((x, y - 0.10, 0.0), (0.05, 0.12, 0.06), GUN_BLACK)           # maner spate
    mb.box((x, y - 0.10, 0.32), (0.05, 0.12, 0.06), GUN_BLACK)          # maner fata
    mb.box((x - 0.07, y + 0.08, 0.28), (0.03, 0.08, 0.05), GUN_BLACK)   # catare


def rpg_warhead(mb, x=0.22, y=0.10, z=0.0):
    mb.box((x, y, z + 0.74), (0.09, 0.09, 0.16), DARK_OLIVE)
    mb.box((x, y, z + 0.88), (0.19, 0.19, 0.18), ROCKET_GREEN)
    mb.box((x, y, z + 1.01), (0.09, 0.09, 0.10), ROCKET_GREEN)


def machine_gun(mb, x=0.10):
    mb.box((x, -0.12, -0.05), (0.08, 0.15, 0.26), GUN_BLACK)            # pat
    mb.box((x, -0.07, 0.32), (0.11, 0.15, 0.46), GUNMETAL)              # corp
    mb.box((x, 0.02, 0.30), (0.10, 0.04, 0.30), GUN_BLACK)              # capac
    mb.box((x - 0.11, -0.17, 0.36), (0.12, 0.17, 0.20), OLIVE)          # cutie cu munitie
    mb.box((x - 0.05, -0.09, 0.36), (0.04, 0.05, 0.12), BRASS)          # banda de cartuse
    mb.box((x, -0.19, 0.20), (0.05, 0.13, 0.06), GUN_BLACK)             # maner
    mb.box((x, -0.06, 0.76), (0.10, 0.10, 0.42), GUNMETAL)              # manson racire
    for k in range(3):
        mb.box((x + 0.051, -0.06, 0.64 + k * 0.12), (0.01, 0.04, 0.05), GUN_BLACK)
    mb.box((x, -0.06, 1.08), (0.05, 0.05, 0.26), GUN_BLACK)             # teava
    mb.box((x, 0.04, 0.62), (0.03, 0.06, 0.16), GUN_BLACK)              # maner de transport
    for dx in (-0.035, 0.035):
        mb.box((x + dx, -0.125, 0.86), (0.025, 0.025, 0.30), GUN_BLACK) # bipied pliat


def infantry_models(team, kind):
    T, TD = TEAM_COLORS[team], TEAM_DARK[team]
    body, rig = MeshBuilder(), MeshBuilder()
    out = {}
    if kind == 'rifle':
        soldier_body(body, team, 'helmet')
        body.box((0, 0.38, -0.24), (0.38, 0.42, 0.16), OLIVE)           # rucsac
        body.box((0, 0.63, -0.24), (0.40, 0.10, 0.13), KHAKI)           # sac de dormit
        assault_rifle(rig)
        add_arms(rig, T, (0.34, -0.30, 0.06), (0.11, -0.20, 0.22), (-0.22, -0.30, 0.26), (0.09, -0.15, 0.60))
        out['muzzle'] = (0.10, -0.05, 1.02)
    elif kind == 'sniper':
        soldier_body(body, team, 'boonie')
        rng = random.Random(7)
        for _ in range(18):                                              # costum ghillie pe spate
            body.box((rng.uniform(-0.26, 0.26), rng.uniform(0.15, 0.62), rng.uniform(-0.24, -0.15)),
                     (rng.uniform(0.10, 0.2), rng.uniform(0.12, 0.3), 0.06), rng.choice(GHILLIE),
                     rot=(rng.uniform(-20, 20), 0, rng.uniform(-30, 30)), jitter=0.2, rng=rng)
        for _ in range(7):                                               # frunze pe palarie
            body.box((rng.uniform(-0.18, 0.18), 1.12, rng.uniform(-0.18, 0.18)), (0.1, 0.07, 0.1),
                     rng.choice(GHILLIE), rot=(0, rng.uniform(0, 90), 0), jitter=0.3, rng=rng)
        sniper_rifle(rig)
        add_arms(rig, T, (0.34, -0.30, 0.06), (0.11, -0.20, 0.17), (-0.22, -0.30, 0.24), (0.09, -0.16, 0.52))
        out['muzzle'] = (0.10, -0.05, 1.47)
    elif kind == 'rpg':
        soldier_body(body, team, 'helmet')
        body.box((0, 0.36, -0.22), (0.36, 0.40, 0.14), OLIVE)           # rucsac cu rachete de rezerva
        for px in (-0.1, 0.1):
            body.box((px, 0.62, -0.26), (0.08, 0.26, 0.08), DARK_OLIVE)
            body.box((px, 0.80, -0.26), (0.15, 0.16, 0.15), ROCKET_GREEN)
        rpg_launcher(rig)
        add_arms(rig, T, (0.38, -0.26, -0.04), (0.22, -0.04, 0.0), (-0.22, -0.28, 0.20), (0.20, -0.04, 0.32))
        warhead = MeshBuilder()
        rpg_warhead(warhead)
        out['loaded'] = warhead.build()                                  # dispare cand trage
        out['muzzle'] = (0.22, 0.10, 0.72)
        out['rear'] = (0.22, 0.10, -0.55)                                # flacara/fum in spate
    elif kind == 'mg':
        soldier_body(body, team, 'helmet')
        for z in (0.19, -0.19):                                          # banda de cartuse pe piept
            body.box((0, 0.36, z), (0.07, 0.66, 0.02), BRASS, rot=(0, 0, 35))
        body.box((-0.27, 0.22, 0.05), (0.08, 0.16, 0.18), DARK_OLIVE)    # cutie suplimentara
        machine_gun(rig)
        add_arms(rig, T, (0.34, -0.30, 0.08), (0.11, -0.21, 0.22), (-0.22, -0.32, 0.30), (0.10, -0.16, 0.66))
        out['muzzle'] = (0.10, -0.06, 1.22)
    legs = leg_mesh(TD, GUN_BLACK)
    out.update(body=body.build(), rig=rig.build(), leg_l=legs, leg_r=legs)
    return out


def tank_models(team):
    T = TEAM_COLORS[team]
    H = mix(OLIVE, T, 0.30)                     # vopsea kaki "tras" spre culoarea echipei
    HD = mix(DARK_OLIVE, TEAM_DARK[team], 0.30)
    hull = MeshBuilder()
    hull.box((0, 0.62, 0), (1.70, 0.50, 2.70), H)                         # caroserie
    hull.box((0, 0.70, 1.38), (1.66, 0.08, 0.50), H, rot=(30, 0, 0))     # placa frontala inclinata
    hull.box((0, 0.88, -0.9), (1.0, 0.03, 0.7), HD)                       # grila motor
    for px in (-0.5, 0.5):
        hull.box((px, 0.72, -1.38), (0.12, 0.12, 0.06), GUN_BLACK)       # evacuare
    for sx in (-1, 1):
        hull.box((sx * 0.98, 0.38, 0), (0.42, 0.62, 2.95), GUN_BLACK)    # senile
        hull.box((sx * 0.98, 0.72, 0), (0.46, 0.06, 3.00), HD)            # aripa
        for k in range(5):
            hull.box((sx * 1.20, 0.34, -1.1 + k * 0.55), (0.04, 0.34, 0.34), GUNMETAL)   # roti
        hull.box((sx * 0.98, 0.76, 1.1), (0.40, 0.03, 0.40), T)          # marcaj de echipa pe aripa

    turret = MeshBuilder()                                                # pivot = centrul turelei
    turret.box((0, 0.25, 0), (1.25, 0.48, 1.45), H)
    turret.box((0, 0.25, 0), (1.27, 0.10, 1.47), T)                       # banda echipei
    turret.box((0, 0.20, 0.80), (0.55, 0.36, 0.20), HD)                   # mantou tun
    turret.box((0, 0.22, 1.70), (0.14, 0.14, 1.70), HD)                   # teava
    turret.box((0, 0.22, 2.55), (0.22, 0.20, 0.18), GUN_BLACK)           # frana de gura
    turret.box((0, 0.25, -0.80), (1.0, 0.30, 0.20), HD)                   # cutii de echipament
    turret.box((0.32, 0.55, -0.25), (0.38, 0.16, 0.38), HD)               # cupola comandant
    turret.box((0.32, 0.73, -0.25), (0.22, 0.22, 0.22), SKIN)             # comandantul
    turret.box((0.32, 0.86, -0.25), (0.27, 0.10, 0.27), OLIVE)
    turret.box((-0.45, 0.95, -0.55), (0.03, 1.0, 0.03), GUN_BLACK)       # antena
    turret.box((-0.33, 1.36, -0.55), (0.22, 0.14, 0.012), T)              # fanion
    return dict(body=hull.build(), rig=turret.build(), muzzle=(0, 0.22, 2.68))


def shadow_mesh(radius):
    def make():
        mb = MeshBuilder()
        mb.disc((0, 0, 0), radius, rgb(0, 0, 0, 0.3), sides=10)
        return mb.build()
    return cached(('shadow', radius), make)


def muzzle_flash_mesh():
    def make():
        mb = MeshBuilder()
        yel, ora = rgb(1.0, 0.92, 0.45), rgb(1.0, 0.6, 0.15)
        mb.blob((0, 0, 0.10), 0.09, yel, sides=6, shade=False)
        mb.box((0, 0, 0.20), (0.05, 0.05, 0.32), ora, shade=False)
        mb.box((0, 0, 0.10), (0.26, 0.04, 0.04), ora, shade=False)
        mb.box((0, 0, 0.10), (0.04, 0.26, 0.04), ora, shade=False)
        return mb.build()
    return cached('flash', make)


def bullet_mesh():
    def make():
        mb = MeshBuilder()
        mb.box((0, 0, 0), (0.04, 0.04, 0.9), rgb(1.0, 0.85, 0.45), shade=False)
        return mb.build()
    return cached('bullet', make)


def sniper_bullet_mesh():
    def make():
        mb = MeshBuilder()
        mb.box((0, 0, 0), (0.035, 0.035, 1.8), rgb(1.0, 0.97, 0.8), shade=False)
        return mb.build()
    return cached('sniper_bullet', make)


def rocket_mesh():
    def make():
        mb = MeshBuilder()
        rpg_warhead(mb, 0, 0, -0.85)
        mb.box((0, 0, -0.32), (0.07, 0.07, 0.36), DARK_OLIVE)
        mb.box((0, 0, -0.46), (0.22, 0.01, 0.10), DARK_OLIVE)            # aripioare
        mb.box((0, 0, -0.46), (0.01, 0.22, 0.10), DARK_OLIVE)
        mb.box((0, 0, -0.57), (0.09, 0.09, 0.16), rgb(1.0, 0.65, 0.2), shade=False)   # flacara
        return mb.build()
    return cached('rocket', make)


def shell_mesh():
    def make():
        mb = MeshBuilder()
        mb.box((0, 0, 0), (0.13, 0.13, 0.40), BRASS)
        mb.box((0, 0, -0.35), (0.09, 0.09, 0.40), rgb(1.0, 0.75, 0.35), shade=False)  # trasor
        return mb.build()
    return cached('shell', make)


def fire_mesh():
    def make():
        mb = MeshBuilder()
        mb.blob((0, 0, 0), 1.0, rgb(1.0, 0.55, 0.12), shade=False)
        mb.blob((0.45, 0.35, 0.2), 0.65, rgb(1.0, 0.82, 0.30), shade=False)
        mb.blob((-0.4, 0.25, -0.3), 0.6, rgb(1.0, 0.42, 0.10), shade=False)
        return mb.build()
    return cached('fire', make)


def smoke_mesh():
    return cached('smoke', lambda: _blob_mesh(rgb(0.36, 0.36, 0.37)))


def dust_mesh():
    return cached('dust', lambda: _blob_mesh(rgb(0.58, 0.50, 0.36)))


def _blob_mesh(col):
    mb = MeshBuilder()
    mb.blob((0, 0, 0), 1.0, col, sides=7)
    return mb.build()


def bar_meshes():
    def make():
        bg, fg = MeshBuilder(), MeshBuilder()
        bg.quad((-0.53, -0.08, 0), (0.53, -0.08, 0), (0.53, 0.08, 0), (-0.53, 0.08, 0), rgb(0.05, 0.05, 0.05), outward=(0, 0, -1), shade=False)
        fg.quad((0, -0.05, -0.01), (1, -0.05, -0.01), (1, 0.05, -0.01), (0, 0.05, -0.01), rgb(1, 1, 1), outward=(0, 0, -1), shade=False)
        return bg.build(), fg.build()
    return cached('bar', make)


def cursor_mesh():
    mb = MeshBuilder()
    mb.ring((0, 0, 0), 0.55, 0.75, rgb(1, 1, 1, 0.8))
    mb.disc((0, 0, 0), 0.2, rgb(1, 1, 1, 0.5))
    return mb.build()


# ================================================================ SUNET
_sound_exists = {}
_last_played = {}


def sound_available(name):
    """Verifica o singura data daca fisierul exista; evita eroarea/spam-ul la fisiere lipsa."""
    if name not in _sound_exists:
        _sound_exists[name] = any(Path(application.asset_folder).rglob(name))
        if not _sound_exists[name]:
            print(f'[audio] "{name}" lipseste - sunetul este dezactivat')
    return _sound_exists[name]


def play_sound(name, volume=0.6, min_interval=0.06):
    """Reda un sunet scurt, limitat in timp ca sa nu se transforme in zgomot."""
    if not sound_available(name):
        return
    now = pytime.monotonic()
    if now - _last_played.get(name, 0) < min_interval:
        return
    _last_played[name] = now
    Audio(name, autoplay=True, auto_destroy=True, volume=volume)


# ================================================================ PROIECTILE SI EFECTE
#   speed: unitati/s | arc: cat de curbata e traiectoria | force: cat impinge la impact
#   vs_armor: multiplicator de damage contra tancurilor
PROJECTILES = {
    'bullet': dict(speed=75, arc=0.0, force=0.25, vs_armor=0.35, mesh=bullet_mesh),
    'sniper': dict(speed=120, arc=0.0, force=1.0, vs_armor=0.5, mesh=sniper_bullet_mesh),
    'rocket': dict(speed=19, arc=0.05, force=2.2, vs_armor=3.0, mesh=rocket_mesh),
    'shell': dict(speed=55, arc=0.01, force=2.8, vs_armor=1.0, mesh=shell_mesh),
}


class Projectile:
    """Glont / racheta / obuz. Daca 'hit' e adevarat urmareste tinta; altfel cade langa ea."""

    def __init__(self, shooter, origin, target, hit):
        kind = shooter.PROJECTILE
        cfg = PROJECTILES[kind]
        self.sx, self.sy, self.sz = origin
        self.team = shooter.team
        self.damage = shooter.attack_damage
        self.splash = shooter.splash
        self.force = cfg['force']
        self.vs_armor = cfg['vs_armor']
        self.trail = kind == 'rocket'
        self.trail_t = 0.0
        if hit:
            self.target = target
            self.dest = (target.x, target.y + target.AIM_Y, target.z)
        else:                                       # ratare: impactul e in pamant, langa tinta
            self.target = None
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(1.0, 2.5) + target.radius
            mx, mz = clamp_arena(target.x + math.cos(a) * r), clamp_arena(target.z + math.sin(a) * r)
            self.dest = (mx, terrain.height_at(mx, mz) + 0.05, mz)
        ex, ey, ez = self.dest
        dist = math.sqrt((ex - self.sx) ** 2 + (ey - self.sy) ** 2 + (ez - self.sz) ** 2)
        self.duration = max(0.04, dist / cfg['speed'])
        self.arc = dist * cfg['arc']
        self.t = 0.0
        self.node = attach_mesh(manager.fx_root, cfg['mesh'](), kind)
        self.node.setPos(*origin)
        self.alive = True

    def update(self, dt):
        tgt = self.target
        if tgt is not None and not tgt.is_dead:
            self.dest = (tgt.x, tgt.y + tgt.AIM_Y, tgt.z)
        self.t += dt
        s = min(1.0, self.t / self.duration)
        ex, ey, ez = self.dest
        x = self.sx + (ex - self.sx) * s
        z = self.sz + (ez - self.sz) * s
        y = self.sy + (ey - self.sy) * s + 4 * self.arc * s * (1 - s)
        self.node.lookAt(x, y, z)                   # orientare dupa directia de zbor
        self.node.setPos(x, y, z)
        if self.trail:
            self.trail_t -= dt
            if self.trail_t <= 0:
                self.trail_t = 0.03
                manager.spawn_smoke(x, y, z, 0.25, life=0.7)
        if s >= 1:
            self.impact(x, y, z)
            self.remove()

    def impact(self, x, y, z):
        tgt = self.target
        if self.splash > 0:
            manager.explode(x, y, z, self.splash, self.damage, self.team, self.force, self.vs_armor)
        elif tgt is not None and not tgt.is_dead:
            mult = self.vs_armor if tgt.ARMORED else 1.0
            tgt.take_damage(self.damage * mult, self.sx, self.sz, self.force)
            if tgt.ARMORED:                         # scantei pe blindaj
                manager.spawn_effect(muzzle_flash_mesh(), x, y, z, 0.12, 0.8, 1.6)
        elif tgt is None and random.random() < 0.4:
            manager.spawn_dust(x, y, z)

    def remove(self):
        self.alive = False
        self.node.removeNode()


class Effect:
    """Fum, praf, minge de foc: creste, se ridica si dispare treptat."""

    def __init__(self, mesh, x, y, z, life, s0, s1, rise):
        self.node = attach_mesh(manager.fx_root, mesh, 'fx')
        self.node.setPos(x, y, z)
        self.node.setHpr(random.uniform(0, 360), random.uniform(-20, 20), 0)
        self.node.setScale(s0)
        self.node.setTransparency(TransparencyAttrib.MAlpha)
        self.node.setDepthWrite(False)
        self.y, self.life, self.s0, self.s1, self.rise = y, life, s0, s1, rise
        self.t = 0.0

    def update(self, dt):
        self.t += dt
        k = self.t / self.life
        if k >= 1:
            self.node.removeNode()
            return False
        e = 1 - (1 - k) ** 2
        self.node.setScale(self.s0 + (self.s1 - self.s0) * e)
        self.node.setAlphaScale(1 - k * k)
        if self.rise:
            self.node.setY(self.y + self.rise * self.t)
        return True

    def remove(self):
        self.node.removeNode()


# ================================================================ UNITATE DE BAZA
class Unit:
    KIND = 'rifle'
    STATS = dict(hp=100, speed=3, attack_range=11, attack_damage=14, attack_cooldown=0.45,
                 radius=BASE_RADIUS, accuracy=0.72, magazine=12, reload_time=2.0, splash=0)
    PROJECTILE = 'bullet'
    ATTACK_SOUND = 'pusca.wav'
    SOUND_VOLUME = 0.35
    BAR_HEIGHT = 2.1
    HIP_Y = 0.72
    SHADOW = 0.5
    RIG_POS = (0, 0.56, 0)      # pivotul armei (umerii)
    AIM_Y = 1.0                 # la ce inaltime tintesc inamicii
    AIM_LOW = -28               # unghiul armei cand nu tinteste
    SWAY = 3                    # balansul armei la mers
    RECOIL = 8                  # cat sare arma la tragere
    FLASH_SIZE = 1.0
    ACCURACY_FALLOFF = 0.35     # cat scade precizia la distanta maxima
    CLOSE_PENALTY = 1.0         # precizie inmultita cu asta cand inamicul e la mai putin de 6 unitati
    MASS = 1.0                  # cat de greu e impins
    ARMORED = False
    TURN = TURN_SPEED
    CORPSE_FLING = 1.0
    SMOKE_ON_FIRE = False

    def __init__(self, x, z, team):
        stats = self.STATS
        self.team = team
        self.hp = self.max_hp = stats['hp']
        self.speed = stats['speed']
        self.attack_range = stats['attack_range']
        self.attack_damage = stats['attack_damage']
        self.attack_cooldown = stats['attack_cooldown']
        self.radius = stats['radius']
        self.accuracy = stats['accuracy']
        self.magazine = stats['magazine']
        self.reload_time = stats['reload_time']
        self.splash = stats['splash']

        self.x, self.z = x, z
        self.y = terrain.height_at(x, z)
        self.heading = math.degrees(math.atan2(-x, -z))      # privim spre centrul arenei
        self.is_dead = False
        self.target_unit = None
        self.attack_timer = random.uniform(0.3, 0.8) * self.attack_cooldown
        self.retarget_timer = random.uniform(0, 0.4)   # decalat, ca sa nu recalculeze toate in acelasi frame
        self.anim_time = random.uniform(0, 10)
        self.flash_timer = 0
        self.muzzle_timer = 0
        self.recoil_time = 0
        self.ammo = self.magazine
        self.reload_timer = 0
        self.aim = self.AIM_LOW
        self.vx = self.vz = 0.0                        # impuls de la explozii/impacturi
        self.hit_dir = None                            # ultima lovitura
        self.health_bar = None
        self.health_bar_fg = None
        self.side = random.choice((-1, 1))          # in ce parte ocoleste piedicile
        self.posed = False                          # picioarele sunt in afara pozitiei de repaus?
        self.loaded = None
        self.rear = None


        self.root = manager.unit_root.attachNewNode('unit')
        shadow = attach_mesh(self.root, shadow_mesh(self.SHADOW), 'shadow')
        shadow.setY(0.06)
        shadow.setTransparency(TransparencyAttrib.MAlpha)
        shadow.setDepthWrite(False)
        shadow.setDepthOffset(2)
        self.body = self.root.attachNewNode('body')
        self.body_base_y = self.HIP_Y
        self.walk_parts = []        # (nod, semn, amplitudine)
        self.build_model()
        self.rig.setP(self.aim)
        s = random.uniform(0.94, 1.06)                 # mica variatie de marime
        self.body.setScale(s)
        self.body.setY(self.body_base_y)
        self.sync()
        manager.register(self)

    # ---- model -------------------------------------------------------
    def models(self):
        return cached((self.KIND, self.team), lambda: infantry_models(self.team, self.KIND))

    def build_model(self):
        m = self.models()
        attach_mesh(self.body, m['body'], 'torso')
        self.leg_l = attach_mesh(self.body, m['leg_l'], 'leg_l')
        self.leg_r = attach_mesh(self.body, m['leg_r'], 'leg_r')
        self.leg_l.setPos(-0.13, 0.02, 0)
        self.leg_r.setPos(0.13, 0.02, 0)
        self.walk_parts = [(self.leg_l, 1, 40), (self.leg_r, -1, 40)]
        self.rig = attach_mesh(self.body, m['rig'], 'rig')
        self.rig.setPos(*self.RIG_POS)
        self.setup_weapon(m)

    def setup_weapon(self, m):
        self.muzzle = self.rig.attachNewNode('muzzle')
        self.muzzle.setPos(*m['muzzle'])
        self.flash = attach_mesh(self.muzzle, muzzle_flash_mesh(), 'flash')
        self.flash.setScale(self.FLASH_SIZE)
        self.flash.hide()
        if 'loaded' in m:                            # racheta vizibila in tub cat e incarcat
            self.loaded = attach_mesh(self.rig, m['loaded'], 'loaded')
        if 'rear' in m:
            self.rear = self.rig.attachNewNode('rear')
            self.rear.setPos(*m['rear'])

    def sync(self):
        """Trimite pozitia la Panda3D (apeluri C++ directe, rapide)."""
        self.root.setPos(self.x, self.y, self.z)
        self.root.setH(-self.heading)

    # ---- bucla principala (apelata de manager) ------------------------
    def update(self, dt, battling):
        if self.is_dead:
            return
        if self.flash_timer > 0:
            self.flash_timer -= dt
            if self.flash_timer <= 0:
                self.root.setColorScale(1, 1, 1, 1)
        if self.muzzle_timer > 0:
            self.muzzle_timer -= dt
            if self.muzzle_timer <= 0:
                self.flash.hide()
        if battling:
            self.think(dt)
            self.sync()
            if self.health_bar is not None:
                self.health_bar.setPos(self.x, self.y + self.BAR_HEIGHT, self.z)

    def think(self, dt):
        if self.vx or self.vz:                      # impuls de la explozii, se stinge repede
            self.x = clamp_arena(self.x + self.vx * dt)
            self.z = clamp_arena(self.z + self.vz * dt)
            decay = max(0.0, 1 - 7 * dt)
            self.vx *= decay
            self.vz *= decay
            if abs(self.vx) + abs(self.vz) < 0.05:
                self.vx = self.vz = 0.0
        self.separate(dt)

        if self.reload_timer > 0:
            self.reload_timer -= dt
            if self.reload_timer <= 0:
                self.ammo = self.magazine
                if self.loaded is not None:
                    self.loaded.show()
        if self.recoil_time > 0:
            self.recoil_time = max(0.0, self.recoil_time - dt)

        # Retintim periodic, nu in fiecare frame
        self.retarget_timer -= dt
        target = self.target_unit
        if target is None or target.is_dead or self.retarget_timer <= 0:
            target = self.target_unit = manager.closest_enemy(self)
            self.retarget_timer = random.uniform(0.3, 0.6)

        aim_goal = self.AIM_LOW
        if target is None:
            self.animate_idle(dt)
        else:
            dx, dz = target.x - self.x, target.z - self.z
            dist = math.hypot(dx, dz)
            reach = self.attack_range + (target.radius - BASE_RADIUS)
            facing = self.face(dx, dz, dt) if dist > 0.001 else 0

            if dist > reach:
                ux, uz = self.avoid_obstacles(dx / dist, dz / dist)
                step = self.speed * dt
                if self.y < WATER_Y - 0.05:
                    step *= WATER_SLOWDOWN
                self.x = clamp_arena(self.x + ux * step)
                self.z = clamp_arena(self.z + uz * step)
                self.animate_walk(dt)
                aim_goal = self.AIM_LOW + math.sin(self.anim_time * 2) * self.SWAY
            else:
                self.animate_idle(dt)
                aim_goal = self.AIM_LOW * 0.5 if self.reload_timer > 0 else 0.0
                self.attack_timer = min(self.attack_timer + dt, self.attack_cooldown)
                if (self.attack_timer >= self.attack_cooldown and self.reload_timer <= 0
                        and facing < AIM_TOLERANCE and self.aim > -10):
                    self.attack_timer = 0
                    self.fire(target, dist)

        self.aim += (aim_goal - self.aim) * min(1, 8 * dt)
        self.rig.setP(self.aim + self.RECOIL * self.recoil_time / RECOIL_TIME)
        self.y = terrain.height_at(self.x, self.z)

    # ---- miscare -----------------------------------------------------
    def face(self, dx, dz, dt):
        """Se roteste spre tinta; intoarce cate grade mai are de rotit."""
        target_angle = math.degrees(math.atan2(dx, dz))
        diff = (target_angle - self.heading + 180) % 360 - 180   # drumul cel mai scurt
        turn = diff * min(1, self.TURN * dt)
        self.heading += turn
        return abs(diff - turn)

    def avoid_obstacles(self, ux, uz):
        """Daca o piatra/un copac e in fata, ocolim pe langa (directie tangenta)."""
        cell = (int(self.x // CELL_SIZE), int(self.z // CELL_SIZE))
        for ox, oz, r in OBSTACLE_GRID.get(cell, ()):
            vx, vz = ox - self.x, oz - self.z
            d = math.hypot(vx, vz)
            clear = r + self.radius + 1.0
            if d > clear or vx * ux + vz * uz <= 0:
                continue
            px, pz = uz, -ux                                   # perpendiculara pe directie
            cross = px * vx + pz * vz
            if abs(cross) < 0.05:
                px, pz = px * self.side, pz * self.side
            elif cross > 0:
                px, pz = -px, -pz                              # spre partea opusa piedicii
            w = (clear - d) / 1.0 * 1.5
            ux, uz = ux + px * w, uz + pz * w
            ln = math.hypot(ux, uz) or 1
            ux, uz = ux / ln, uz / ln
        return ux, uz

    def separate(self, dt):
        """Coliziune moale cu vecinii (doar celulele din jur) + piedici solide.
        Unitatile grele (tancul) imping soldatii mult mai tare decat sunt impinse."""
        x, z, rad, mass = self.x, self.z, self.radius, self.MASS
        k = SEPARATION_STRENGTH * dt
        grid = manager.grid
        cx, cz = int(x // CELL_SIZE), int(z // CELL_SIZE)
        r = 1 if rad <= 1.0 else 2                  # tancurile trebuie sa vada alte tancuri mai departe
        neighbours = []
        for i in range(cx - r, cx + r + 1):
            for j in range(cz - r, cz + r + 1):
                lst = grid.get((i, j))
                if lst:
                    neighbours += lst
        for other in neighbours:
            if other is self:
                continue
            dx, dz = x - other.x, z - other.z
            dist_sq = dx * dx + dz * dz
            min_dist = rad + other.radius
            if dist_sq >= min_dist * min_dist:
                continue
            if dist_sq < 1e-6:                      # exact una peste alta -> impingere aleatoare
                dx, dz, dist_sq = random.uniform(-1, 1), random.uniform(-1, 1), 1
            dist = math.sqrt(dist_sq)
            push = (min_dist - dist) * k / dist * (2.0 * other.MASS / (mass + other.MASS))
            x += dx * push
            z += dz * push
        for ox, oz, r in OBSTACLE_GRID.get((int(x // CELL_SIZE), int(z // CELL_SIZE)), ()):
            dx, dz = x - ox, z - oz
            dist = math.hypot(dx, dz)
            min_dist = r + rad
            if 1e-6 < dist < min_dist:              # piedicile nu se "inmoaie": iesim complet
                x = ox + dx / dist * min_dist
                z = oz + dz / dist * min_dist
        self.x, self.z = clamp_arena(x), clamp_arena(z)

    def push_from(self, src_x, src_z, force):
        dx, dz = self.x - src_x, self.z - src_z
        ln = math.hypot(dx, dz)
        if ln < 1e-6:
            a = random.uniform(0, 2 * math.pi)
            dx, dz, ln = math.cos(a), math.sin(a), 1.0
        dx, dz = dx / ln, dz / ln
        impulse = force / self.MASS * 6
        self.vx += dx * impulse
        self.vz += dz * impulse
        self.hit_dir = (dx, dz, force)

    # ---- animatii ----------------------------------------------------
    def animate_walk(self, dt):
        self.anim_time += dt * self.speed * 3.2
        swing = math.sin(self.anim_time)
        for part, sign, amplitude in self.walk_parts:
            part.setP(swing * sign * amplitude)
        self.body.setY(self.body_base_y + abs(swing) * 0.06)      # mic "balans" la mers
        self.posed = True

    def animate_idle(self, dt):
        if not self.posed:                                        # deja in repaus: nimic de facut
            return
        k = min(1, 10 * dt)                                       # revenire lina la pozitia de repaus
        biggest = 0
        for part, _, _ in self.walk_parts:
            p = part.getP() * (1 - k)
            part.setP(p)
            biggest = max(biggest, abs(p))
        y = self.body.getY()
        self.body.setY(y + (self.body_base_y - y) * k)
        if biggest < 0.5:
            for part, _, _ in self.walk_parts:
                part.setP(0)
            self.body.setY(self.body_base_y)
            self.posed = False

    # ---- lupta -------------------------------------------------------
    def fire(self, target, dist):
        self.recoil_time = RECOIL_TIME
        self.flash.show()
        self.muzzle_timer = 0.05
        play_sound(self.ATTACK_SOUND, self.SOUND_VOLUME)
        if self.magazine:
            self.ammo -= 1
            if self.ammo <= 0:
                self.reload_timer = self.reload_time
                if self.loaded is not None:
                    self.loaded.hide()
        chance = min(0.97, self.accuracy * (1 + self.ACCURACY_FALLOFF * (0.4 - dist / self.attack_range)))
        if dist < 6:
            chance *= self.CLOSE_PENALTY
        hit = random.random() < chance
        p = self.muzzle.getPos(scene)
        manager.projectiles.append(Projectile(self, (p.x, p.y, p.z), target, hit))
        if self.rear is not None:                   # suflul din spatele RPG-ului
            r = self.rear.getPos(scene)
            manager.spawn_smoke(r.x, r.y, r.z, 0.5, life=0.8)
        if self.SMOKE_ON_FIRE:
            manager.spawn_smoke(p.x, p.y, p.z, 0.7, life=1.0)

    def take_damage(self, amount, src_x=None, src_z=None, force=0.0):
        if self.is_dead:
            return
        if src_x is not None and force > 0:
            self.push_from(src_x, src_z, force)
        self.hp -= amount
        if self.hp <= 0:
            self.die()
            return
        self.root.setColorScale(2.2, 2.2, 2.2, 1)       # clipire alba
        self.flash_timer = 0.1
        self.update_health_bar()

    def update_health_bar(self):
        if self.health_bar is None:     # apare doar dupa prima lovitura
            bg, fg = bar_meshes()
            # bara nu e copil al unitatii, ca sa nu clipeasca/se intunece odata cu ea
            self.health_bar = manager.bar_root.attachNewNode('bar')
            self.health_bar.setBillboardPointEye(1)
            bg.copyTo(self.health_bar)
            self.health_bar_fg = attach_mesh(self.health_bar, fg, 'fg')
            self.health_bar_fg.setX(-0.5)
            self.health_bar.setPos(self.x, self.y + self.BAR_HEIGHT, self.z)
        ratio = max(self.hp, 0) / self.max_hp
        self.health_bar_fg.setSx(max(ratio, 0.001))
        c = color.hsv(120 * ratio, 0.85, 0.9)                          # verde -> rosu
        self.health_bar_fg.setColorScale(c[0], c[1], c[2], 1)

    def die(self):
        self.is_dead = True
        manager.unregister(self)
        self.flash.hide()
        self.root.setColorScale(0.38, 0.38, 0.42, 1)    # corpul se intuneca
        self.remove_health_bar()
        manager.add_corpse(self)

    # ---- cadavru -----------------------------------------------------
    def start_corpse(self):
        """'Yeet': viteza + rotatie aleatoare, impins in directia ultimei lovituri."""
        vx, vz, vy = random.uniform(-2, 2), random.uniform(-2, 2), random.uniform(4, 7)
        if self.hit_dir is not None:
            dx, dz, force = self.hit_dir
            vx += dx * force * 5
            vz += dz * force * 5
            vy += force * 3
        self.vel = [vx, vy, vz]
        self.spin = tuple(random.uniform(-700, 700) for _ in range(3))
        self.corpse_time = 0.0

    def corpse_update(self, dt):
        self.corpse_time += dt
        if self.corpse_time >= DEATH_DELAY:
            self.destroy()
            return False
        v = self.vel
        v[1] -= 25 * dt
        self.x += v[0] * dt
        self.y += v[1] * dt
        self.z += v[2] * dt
        self.root.setPos(self.x, self.y, self.z)
        b = self.body
        b.setHpr(b.getH() + self.spin[0] * dt, b.getP() + self.spin[1] * dt, b.getR() + self.spin[2] * dt)
        return True

    def remove_health_bar(self):
        if self.health_bar is not None:
            self.health_bar.removeNode()
            self.health_bar = None

    def destroy(self):
        self.remove_health_bar()
        self.root.removeNode()


# ================================================================ UNITATI SPECIFICE
class Rifleman(Unit):
    KIND = 'rifle'
    STATS = dict(hp=100, speed=3.0, attack_range=11, attack_damage=14, attack_cooldown=0.45,
                 radius=BASE_RADIUS, accuracy=0.72, magazine=12, reload_time=2.0, splash=0)


class Sniper(Unit):
    KIND = 'sniper'
    STATS = dict(hp=70, speed=2.4, attack_range=30, attack_damage=80, attack_cooldown=3.0,
                 radius=BASE_RADIUS, accuracy=0.9, magazine=5, reload_time=3.0, splash=0)
    PROJECTILE = 'sniper'
    ATTACK_SOUND = 'sniper.wav'
    SOUND_VOLUME = 0.6
    AIM_LOW = -35
    RECOIL = 14
    FLASH_SIZE = 1.4
    ACCURACY_FALLOFF = 0.08     # aproape la fel de precis si la distanta mare
    CLOSE_PENALTY = 0.5         # dar prin luneta nimereste greu un inamic lipit de el


class RocketSoldier(Unit):
    KIND = 'rpg'
    STATS = dict(hp=90, speed=2.6, attack_range=14, attack_damage=65, attack_cooldown=0.3,
                 radius=BASE_RADIUS, accuracy=0.8, magazine=1, reload_time=3.5, splash=2.6)
    PROJECTILE = 'rocket'
    ATTACK_SOUND = 'rpg.wav'
    SOUND_VOLUME = 0.6
    AIM_LOW = -12               # tubul sta pe umar, nu coboara mult
    SWAY = 2
    RECOIL = 10
    FLASH_SIZE = 1.6


class MachineGunner(Unit):
    KIND = 'mg'
    STATS = dict(hp=150, speed=2.0, attack_range=12, attack_damage=7, attack_cooldown=0.1,
                 radius=BASE_RADIUS, accuracy=0.5, magazine=40, reload_time=3.5, splash=0)
    ATTACK_SOUND = 'mitraliera.wav'
    SOUND_VOLUME = 0.3
    RECOIL = 3
    FLASH_SIZE = 1.1
    MASS = 1.3


class Tank(Unit):
    KIND = 'tank'
    STATS = dict(hp=900, speed=2.2, attack_range=18, attack_damage=110, attack_cooldown=0.5,
                 radius=1.4, accuracy=0.85, magazine=1, reload_time=4.5, splash=3.2)
    PROJECTILE = 'shell'
    ATTACK_SOUND = 'tun.wav'
    SOUND_VOLUME = 0.7
    BAR_HEIGHT = 2.9
    HIP_Y = 0.0
    SHADOW = 1.7
    RIG_POS = (0, 0.87, -0.15)  # pivotul turelei
    AIM_Y = 0.9
    AIM_LOW = 0
    SWAY = 0
    RECOIL = 5
    FLASH_SIZE = 3.0
    MASS = 8.0
    ARMORED = True
    TURN = 2.5                  # tancul se roteste incet
    SMOKE_ON_FIRE = True

    def models(self):
        return cached(('tank', self.team), lambda: tank_models(self.team))

    def build_model(self):
        m = self.models()
        attach_mesh(self.body, m['body'], 'hull')
        self.walk_parts = []                         # senilele nu au membre de animat
        self.rig = attach_mesh(self.body, m['rig'], 'turret')
        self.rig.setPos(*self.RIG_POS)
        self.setup_weapon(m)

    def animate_walk(self, dt):
        self.anim_time += dt * 20
        self.body.setY(self.body_base_y + 0.02 * math.sin(self.anim_time))   # vibratia motorului
        self.posed = True

    def start_corpse(self):
        # Tancul explodeaza, iar turela sare in aer; epava ramane si fumega.
        manager.explosion_fx(self.x, self.y + 1.0, self.z, 1.7)
        self.corpse_time = 0.0
        self.turret_v = [random.uniform(-2.5, 2.5), random.uniform(7, 10), random.uniform(-2.5, 2.5)]
        self.turret_pos = list(self.RIG_POS)
        self.turret_spin = random.uniform(-400, 400)
        self.turret_flying = True

    def corpse_update(self, dt):
        self.corpse_time += dt
        if self.corpse_time >= WRECK_DELAY:
            self.destroy()
            return False
        if self.turret_flying:
            v, p = self.turret_v, self.turret_pos
            v[1] -= 25 * dt
            p[0] += v[0] * dt
            p[1] += v[1] * dt
            p[2] += v[2] * dt
            on_hull = abs(p[0]) < 0.85 and abs(p[2]) < 1.35
            floor = self.RIG_POS[1] if on_hull else 0.0
            if v[1] < 0 and p[1] <= floor:
                p[1] = floor
                self.turret_flying = False
            self.rig.setPos(*p)
            self.rig.setH(self.rig.getH() + self.turret_spin * dt)
        if random.random() < dt * 8:
            manager.spawn_smoke(self.x + random.uniform(-0.6, 0.6), self.y + 1.2, self.z + random.uniform(-0.6, 0.6),
                                0.8, life=1.6)
        return True


# ---------------------------------------------------------------- TIPURI DE UNITATI (tasta -> (nume, clasa, descriere))
UNIT_TYPES = {
    '1': ('SOLDAT', Rifleman, 'pusca de asalt, echilibrat'),
    '2': ('LUNETIST', Sniper, 'bataie uriasa, trage rar'),
    '3': ('RPG', RocketSoldier, 'racheta cu explozie, anti-tanc'),
    '4': ('MITRALIOR', MachineGunner, 'foc continuu, imprecis'),
    '5': ('TANC', Tank, 'blindat, obuz exploziv'),
}


# ================================================================ MANAGER
class BattleManager(Entity):
    def __init__(self):
        super().__init__()
        self.is_battling = False
        self.game_over = False
        self.current_team = 'red'
        self.selected_key = '1'

        self.units = []                              # doar unitatile in viata
        self.placed = []                             # ordinea plasarii (pentru Z)
        self.projectiles = []
        self.effects = []
        self.corpses = []
        self.team_units = {'red': [], 'blue': []}
        self.grid = {}                               # grila spatiala pentru vecini
        self._last_counts = None
        self.message_timer = 0
        self.last_paint = None
        self.water_t = 0

        # Cateva entitati "parinte": toate unitatile/proiectilele/barele sunt noduri simple sub ele
        self.unit_root = Entity()
        self.fx_root = Entity()
        self.bar_root = Entity()
        for e in (self.unit_root, self.fx_root, self.bar_root):
            apply_fog(e)
        self.cursor = Entity(model=cursor_mesh(), enabled=False)
        self.cursor.setTransparency(TransparencyAttrib.MAlpha)
        self.cursor.setDepthOffset(3)

        self.ui_status = Text(text='', origin=(0, 0), y=0.45)
        self.ui_controls = Text(
            text='1: Soldat | 2: Lunetist | 3: RPG | 4: Mitralior | 5: Tanc || T: Echipa || Z: Anuleaza || SPACE: Start || R: Reset\n'
                 'Click dreapta + mouse: camera | Scroll: zoom | Tine click stanga apasat: plaseaza mai multe',
            origin=(0, 0), y=0.40, scale=0.8)
        self.ui_counts = Text(text='', origin=(0, 0), y=0.32)
        self.ui_message = Text(text='', origin=(0, 0), y=0.25, scale=1.2, color=color.yellow)
        self.ui_victory = Text(text='', origin=(0, 0), y=0.1, scale=3)
        self.update_ui()

    # ---- registru unitati --------------------------------------------
    def register(self, unit):
        self.units.append(unit)
        self.placed.append(unit)
        self.team_units[unit.team].append(unit)

    def unregister(self, unit):
        if unit in self.units:
            self.units.remove(unit)
        if unit in self.team_units[unit.team]:
            self.team_units[unit.team].remove(unit)

    def add_corpse(self, unit):
        unit.start_corpse()
        self.corpses.append(unit)

    def refresh_grid(self):
        grid = {}
        for u in self.units:
            cell = (int(u.x // CELL_SIZE), int(u.z // CELL_SIZE))
            lst = grid.get(cell)
            if lst is None:
                grid[cell] = [u]
            else:
                lst.append(u)
        self.grid = grid

    def closest_enemy(self, unit):
        enemies = self.team_units['blue' if unit.team == 'red' else 'red']
        ux, uz = unit.x, unit.z
        best, best_d = None, float('inf')
        for e in enemies:
            d = (e.x - ux) ** 2 + (e.z - uz) ** 2
            if d < best_d:
                best, best_d = e, d
        return best

    # ---- efecte si explozii ------------------------------------------
    def spawn_effect(self, mesh, x, y, z, life, s0, s1, rise=0.0, essential=False):
        if not essential and len(self.effects) >= MAX_EFFECTS:
            return
        self.effects.append(Effect(mesh, x, y, z, life, s0, s1, rise))

    def spawn_smoke(self, x, y, z, size, life=1.2):
        self.spawn_effect(smoke_mesh(), x, y, z, life * random.uniform(0.8, 1.2), size * 0.5, size * 1.6, rise=0.8)

    def spawn_dust(self, x, y, z):
        self.spawn_effect(dust_mesh(), x, y, z, 0.45, 0.08, 0.35, rise=0.4)

    def explosion_fx(self, x, y, z, size):
        self.spawn_effect(fire_mesh(), x, y, z, 0.32, 0.25 * size, 1.1 * size, rise=0.6, essential=True)
        for _ in range(int(3 + 2 * size)):
            self.spawn_effect(smoke_mesh(), x + random.uniform(-0.5, 0.5) * size, y + random.uniform(0, 0.4) * size,
                              z + random.uniform(-0.5, 0.5) * size, random.uniform(0.9, 1.5), 0.3 * size, 0.9 * size,
                              rise=random.uniform(0.6, 1.4), essential=True)
        for _ in range(4):
            self.spawn_dust(x + random.uniform(-1, 1) * size, y, z + random.uniform(-1, 1) * size)
        play_sound('explozie.wav', 0.6, 0.08)

    def explode(self, x, y, z, radius, damage, team, force, vs_armor):
        """Damage pe zona doar pentru inamici, mai mic spre margine; ii si arunca in spate."""
        self.explosion_fx(x, y, z, radius / 2.6)
        enemies = self.team_units['blue' if team == 'red' else 'red']
        for e in list(enemies):
            d = math.hypot(e.x - x, e.z - z) - e.radius
            if d < radius:
                f = 1 - 0.6 * max(0.0, d) / radius
                mult = vs_armor if e.ARMORED else 1.0
                e.take_damage(damage * f * mult, x, z, force * f)

    # ---- bucla (singurul update din joc) ------------------------------
    def update(self):
        dt = min(time.dt, MAX_DT)
        self.update_cursor()
        self.update_counts()

        # apa se misca usor
        self.water_t += dt
        water.setY(WATER_Y + math.sin(self.water_t * 1.3) * 0.03)

        if self.message_timer > 0:
            self.message_timer -= dt
            if self.message_timer <= 0:
                self.ui_message.text = ''

        battling = self.is_battling and not self.game_over
        if battling:
            self.refresh_grid()
        for u in list(self.units):
            u.update(dt, battling)

        if self.projectiles:
            for p in list(self.projectiles):
                p.update(dt)
            self.projectiles = [p for p in self.projectiles if p.alive]

        if self.effects:
            self.effects = [e for e in self.effects if e.update(dt)]

        if self.corpses:
            self.corpses = [u for u in self.corpses if u.corpse_update(dt)]

        if not battling:
            return

        red_alive = len(self.team_units['red'])
        blue_alive = len(self.team_units['blue'])
        if red_alive == 0 and blue_alive > 0:
            self.declare_winner('ALBASTRA', TEAM_UI['blue'])
        elif blue_alive == 0 and red_alive > 0:
            self.declare_winner('ROSIE', TEAM_UI['red'])
        elif red_alive == 0 and blue_alive == 0:
            self.declare_winner('EGALITATE', color.gray)

    # ---- mouse -> teren ----------------------------------------------
    def ground_point(self):
        """Raza din camera prin mouse, intersectata cu terenul (fara collider, fara fizica)."""
        near, far = Point3(), Point3()
        mpos = Point2(mouse.x * 2 / window.aspect_ratio, mouse.y * 2)
        if not camera.lens.extrude(mpos, near, far):
            return None
        cam = application.base.cam
        near = scene.getRelativePoint(cam, near)
        far = scene.getRelativePoint(cam, far)
        d = far - near
        length = d.length()
        if length == 0:
            return None
        d /= length
        # mers in pasi pe raza pana trecem sub teren, apoi rafinare binara
        step, t, prev = 0.5, 0.0, None
        max_t = min(length, 250)
        while t < max_t:
            p = near + d * t
            if abs(p.x) <= WORLD_HALF and abs(p.z) <= WORLD_HALF and p.y <= terrain.height_at(p.x, p.z):
                lo, hi = (prev if prev is not None else 0), t
                for _ in range(12):
                    mid = (lo + hi) / 2
                    q = near + d * mid
                    if q.y <= terrain.height_at(q.x, q.z):
                        hi = mid
                    else:
                        lo = mid
                p = near + d * hi
                if abs(p.x) > ARENA_HALF + 0.5 or abs(p.z) > ARENA_HALF + 0.5:
                    return None
                return Vec3(clamp_arena(p.x), 0, clamp_arena(p.z))
            prev = t
            t += step
        return None

    def update_cursor(self):
        if self.is_battling:
            self.cursor.enabled = False
            return
        point = self.ground_point()
        self.cursor.enabled = point is not None
        if point is not None:
            self.cursor.setPos(point.x, terrain.height_at(point.x, point.z) + 0.08, point.z)
            # "pictare": tinand click stanga, plasam unitati la distanta potrivita marimii lor
            if mouse.left and self.last_paint is not None:
                spacing = max(1.2, UNIT_TYPES[self.selected_key][1].STATS['radius'] * 2 + 0.4)
                if math.hypot(point.x - self.last_paint[0], point.z - self.last_paint[1]) > spacing:
                    self.place_unit(point)

    def update_counts(self):
        counts = (len(self.team_units['red']), len(self.team_units['blue']))
        if counts != self._last_counts:      # Text se regenereaza doar cand se schimba ceva
            self._last_counts = counts
            self.ui_counts.text = f'ROSII: {counts[0]}   |   ALBASTRII: {counts[1]}'

    # ---- UI ----------------------------------------------------------
    def show_message(self, text, seconds=2):
        self.ui_message.text = text
        self.message_timer = seconds

    def update_ui(self):
        if self.game_over:
            self.ui_status.text = 'Lupta s-a incheiat.'
        elif self.is_battling:
            self.ui_status.text = 'LUPTA A INCEPUT!'
        else:
            name, _, desc = UNIT_TYPES[self.selected_key]
            self.ui_status.text = f'Selectat: {name} ({desc}) | Echipa: {TEAM_NAMES[self.current_team]}'
        self.ui_controls.enabled = not self.is_battling
        c = TEAM_COLORS[self.current_team]
        self.cursor.color = Color(c[0], c[1], c[2], 0.9)

    def declare_winner(self, winner_name, win_color):
        self.game_over = True
        self.ui_victory.text = f"ECHIPA {winner_name} A CASTIGAT!\nApasa 'R' pentru Restart"
        self.ui_victory.color = win_color
        self.update_ui()

    # ---- actiuni -----------------------------------------------------
    def start_battle(self):
        if not self.team_units['red'] or not self.team_units['blue']:
            self.show_message('Pune unitati pe ambele echipe inainte de start!')
            return
        self.is_battling = True
        self.update_ui()

        if sound_available('muzica.mp3'):
            if not hasattr(self, 'bg_music'):
                self.bg_music = Audio('muzica.mp3', loop=True, autoplay=True, volume=0.4)
            else:
                self.bg_music.resume()

    def reset(self):
        for unit in self.units + self.corpses:
            unit.destroy()
        for p in self.projectiles:
            p.remove()
        for e in self.effects:
            e.remove()
        self.units, self.placed, self.corpses, self.projectiles, self.effects = [], [], [], [], []
        self.team_units = {'red': [], 'blue': []}
        self.grid = {}
        self.is_battling = False
        self.game_over = False
        self.ui_victory.text = ''
        self.ui_message.text = ''
        if hasattr(self, 'bg_music'):
            self.bg_music.pause()
        self.update_ui()

    def place_unit(self, point):
        unit_class = UNIT_TYPES[self.selected_key][1]
        unit_class(point.x, point.z, self.current_team)
        self.last_paint = (point.x, point.z)

    def undo(self):
        while self.placed:
            unit = self.placed.pop()
            if not unit.is_dead:
                self.unregister(unit)
                unit.destroy()
                return

    def input(self, key):
        if key == 'left mouse up':
            self.last_paint = None
        if key == 'r':
            self.reset()
            return
        if self.is_battling:
            return

        if key == 'space':
            self.start_battle()
        elif key in UNIT_TYPES:
            self.selected_key = key
        elif key == 't':
            self.current_team = 'blue' if self.current_team == 'red' else 'red'
        elif key == 'z':
            self.undo()
        elif key == 'left mouse down':
            point = self.ground_point()
            if point is not None:
                self.place_unit(point)
        self.update_ui()


manager = BattleManager()
Sky()
editor_camera = EditorCamera()
editor_camera.rotation_x = 40       # privim de sus, nu de la nivelul solului
editor_camera.target_z = -35        # putin mai departe, ca sa incapa tot terenul

if __name__ == '__main__':
    app.run()
