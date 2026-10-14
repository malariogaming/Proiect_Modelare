"""
Battle Simulator (Ursina) - versiune optimizata

Controale:
  1 / 2 / 3     alege unitatea (Cavaler / Arcas / Cavalerie)
  T             schimba echipa
  Click stanga  plaseaza unitatea (tine apasat + misca mouse-ul = "pictezi" unitati)
  Z             sterge ultima unitate plasata
  SPACE         porneste lupta
  R             reset
  Click dreapta + mouse = roteste camera | Scroll = zoom | Click mijloc = muta camera

Fisiere optionale (langa script): sabie.wav, sageata.wav, muzica.mp3
Daca lipsesc, jocul ruleaza fara sunet.

De ce mergea greu versiunea veche si ce s-a schimbat:
  * Fiecare unitate era o subclasa de Entity. Ursina trece FIECARE atribuire
    (self.hp -= ..., self.x = ...) printr-un __setattr__ scris in Python, deci
    logica jocului era foarte scumpa. Acum unitatile sunt clase Python simple,
    pozitia sta in float-uri si se trimite la Panda3D o singura data pe frame.
  * O singura functie update() (in manager) in loc de una per entitate.
  * Fiecare piesa de unitate era o entitate separata cu model propriu (sfera =
    sute de triunghiuri). Acum fiecare unitate are cateva mesh-uri low-poly
    pre-construite si PARTAJATE intre unitati (geometria se creeaza o data per
    tip + echipa), fara entitati Ursina pentru copii.
  * Tot decorul (copaci, pietre, iarba) este UN singur mesh = un singur draw call.
  * Umbrirea este "coapta" in culorile varfurilor, deci nu costa nimic la rulare.
"""
from ursina import *
from panda3d.core import NodePath, Point2, Point3, TransparencyAttrib, loadPrcFileData
from pathlib import Path
import math
import random
import time as pytime  # 'time' din ursina contine time.dt, deci folosim alt alias

# Unitatile isi misca bratele/picioarele in fiecare frame; cache-ul de transformari din
# Panda3D doar ar consuma timp aici (masurat: ~15% mai rapid fara el).
loadPrcFileData('', 'transform-cache false')
app = Ursina(development_mode=False)
window.title = 'Battle Simulator'
window.fps_counter.enabled = True
window.color = color.hsv(205, 0.25, 0.92)

# ---------------------------------------------------------------- CONSTANTE
ARENA_HALF = 19             # zona de lupta (unitatile nu ies din ea)
WORLD_HALF = 34             # tot terenul, inclusiv muntii din jur
TERRAIN_CELL = 1.0          # rezolutia terenului
CELL_SIZE = 2.0             # celula grilei spatiale (>= suma maxima a razelor)
BASE_RADIUS = 0.5           # raza unei unitati "normale"
SEPARATION_STRENGTH = 4     # cat de tare se imping unitatile intre ele
TURN_SPEED = 10             # viteza de rotire spre inamic
SWING_DURATION = 0.3        # durata animatiei de atac
DEATH_DELAY = 1.5           # dupa cat timp dispare cadavrul
WATER_Y = -0.9              # nivelul apei din rau
WATER_SLOWDOWN = 0.55       # prin apa se merge mai incet
MAX_DT = 1 / 20             # evita "teleportarile" cand un frame dureaza mult

TEAM_NAMES = {'red': 'ROSIE', 'blue': 'ALBASTRA'}
FOG_COLOR = color.hsv(205, 0.18, 0.9)


def rgb(r, g, b, a=1.0):
    """Culori 0-1, independent de versiunea Ursina (color.rgb s-a schimbat intre versiuni)."""
    return Color(r, g, b, a)


TEAM_COLORS = {'red': rgb(0.80, 0.16, 0.14), 'blue': rgb(0.16, 0.36, 0.85)}
TEAM_DARK = {'red': rgb(0.50, 0.09, 0.08), 'blue': rgb(0.09, 0.19, 0.48)}
TEAM_UI = {'red': color.red, 'blue': color.azure}

SKIN = rgb(0.96, 0.76, 0.60)
STEEL = rgb(0.72, 0.75, 0.80)
DARK_STEEL = rgb(0.38, 0.40, 0.45)
GOLD = rgb(0.95, 0.75, 0.20)
LEATHER = rgb(0.45, 0.28, 0.14)
DARK_LEATHER = rgb(0.28, 0.17, 0.09)
WOOD = rgb(0.55, 0.36, 0.18)
CLOTH_WHITE = rgb(0.92, 0.90, 0.85)
BLACK = rgb(0.08, 0.08, 0.08)
HORSE_COLOR = rgb(0.52, 0.32, 0.18)
HORSE_DARK = rgb(0.25, 0.15, 0.08)


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

    def box(self, center, size, col, rot=(0, 0, 0), jitter=0.0, rng=None):
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
            self.quad(*pts, col, outward=(fc[0] - cx, fc[1] - cy, fc[2] - cz))

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
    """Copie ieftina a unui mesh partajat (Panda3D refoloseste geometria)."""
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
    # Raul serpuieste prin mijlocul arenei, cu albie de adancime constanta
    d = z - river_center(x)
    w = math.exp(-(d * d) / 5.0)
    h = h * (1 - w) + (WATER_Y - 0.45) * w
    # Munti in afara arenei, ca terenul sa nu mai pluteasca in gol
    # (distanta "rotunjita" fata de margine, ca muntii sa nu formeze linii drepte)
    edge = (abs(x) ** 6 + abs(z) ** 6) ** (1 / 6) - ARENA_HALF - 1.5
    if edge > 0:
        edge = min(edge, 10)                       # inaltime limitata (fara "ace" in colturi)
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
        # iarba: mai deschisa sus, mai inchisa in vai, cu pete
        t = max(0, min(1, (y + 1) / 4))
        patch = 0.04 * math.sin(x * 0.7) * math.cos(z * 0.6)
        return rgb(0.30 + 0.12 * t + n + patch, 0.55 + 0.10 * t + n + patch, 0.22 + n)


terrain = Terrain()


# ================================================================ DECOR (un singur mesh)
OBSTACLES = []      # (x, z, raza) - piedici solide in arena
OBSTACLE_GRID = {}


def add_obstacle(x, z, r):
    OBSTACLES.append((x, z, r))
    reach = r + 1.0                                   # 1.0 = raza maxima a unei unitati
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

    # Pietre de vad in rau (doar decor)
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


def humanoid_body(mb, team, armored):
    T, TD = TEAM_COLORS[team], TEAM_DARK[team]
    if armored:
        mb.box((0, 0.32, 0), (0.52, 0.62, 0.32), STEEL)                    # armura
        mb.box((0, 0.24, 0.165), (0.30, 0.52, 0.02), T)                    # tabard in culoarea echipei
        mb.box((0, 0.32, 0.18), (0.08, 0.30, 0.01), GOLD)                  # cruce pe tabard
        mb.box((0, 0.36, 0.18), (0.22, 0.07, 0.01), GOLD)
    else:
        mb.box((0, 0.30, 0), (0.48, 0.60, 0.30), T)                        # tunica
        mb.box((0, 0.02, 0), (0.50, 0.14, 0.32), TD)                       # poala tunicii
    mb.box((0, 0.06, 0), (0.52, 0.07, 0.33), LEATHER)                      # curea
    mb.box((0.12, 0.06, 0.17), (0.08, 0.08, 0.02), GOLD)                   # catarama
    mb.box((0, 0.84, 0), (0.36, 0.36, 0.36), SKIN)                         # cap
    mb.box((0, 0.64, 0), (0.16, 0.08, 0.16), SKIN)                         # gat


def knight_models(team):
    T = TEAM_COLORS[team]
    body = MeshBuilder()
    humanoid_body(body, team, armored=True)
    body.box((0, 0.88, 0), (0.42, 0.44, 0.42), STEEL)                      # coif
    body.box((0, 0.86, 0.212), (0.30, 0.05, 0.01), BLACK)                  # fanta vizierei
    body.box((0, 0.76, 0.212), (0.04, 0.12, 0.01), BLACK)
    body.box((0, 1.15, -0.04), (0.08, 0.16, 0.34), T)                      # panas
    body.box((0, 0.56, 0), (0.46, 0.06, 0.40), DARK_STEEL)                 # gorget

    arm_r = MeshBuilder()
    arm_r.box((0, -0.02, 0), (0.24, 0.16, 0.24), STEEL)                    # umar
    arm_r.box((0, -0.25, 0), (0.16, 0.46, 0.16), DARK_STEEL)
    arm_r.box((0, -0.52, 0), (0.15, 0.13, 0.15), DARK_STEEL)               # manusa
    arm_r.box((0, -0.53, 0.02), (0.05, 0.05, 0.28), LEATHER)               # maner
    arm_r.box((0, -0.53, 0.17), (0.28, 0.05, 0.06), GOLD)                  # garda
    arm_r.box((0, -0.53, 0.6), (0.09, 0.03, 0.82), rgb(0.88, 0.9, 0.95))   # lama
    arm_r.box((0, -0.53, -0.14), (0.08, 0.08, 0.06), GOLD)                 # maciulie

    arm_l = MeshBuilder()
    arm_l.box((0, -0.02, 0), (0.24, 0.16, 0.24), STEEL)
    arm_l.box((0, -0.25, 0), (0.16, 0.46, 0.16), DARK_STEEL)
    arm_l.box((0, -0.52, 0), (0.15, 0.13, 0.15), DARK_STEEL)
    arm_l.box((-0.13, -0.35, 0.10), (0.04, 0.66, 0.52), DARK_STEEL)        # scut - margine
    arm_l.box((-0.155, -0.35, 0.10), (0.03, 0.58, 0.44), T)                # scut - fata
    arm_l.box((-0.175, -0.33, 0.10), (0.02, 0.26, 0.07), GOLD)             # blazon
    arm_l.box((-0.175, -0.30, 0.10), (0.02, 0.07, 0.22), GOLD)

    legs = leg_mesh(DARK_STEEL, DARK_LEATHER)
    return dict(body=body.build(), arm_l=arm_l.build(), arm_r=arm_r.build(), leg_l=legs, leg_r=legs)


def archer_models(team):
    T, TD = TEAM_COLORS[team], TEAM_DARK[team]
    body = MeshBuilder()
    humanoid_body(body, team, armored=False)
    body.box((-0.08, 0.86, 0.181), (0.06, 0.06, 0.01), BLACK)              # ochi
    body.box((0.08, 0.86, 0.181), (0.06, 0.06, 0.01), BLACK)
    body.box((0, 1.04, -0.02), (0.42, 0.08, 0.42), TD)                     # gluga - sus
    body.box((0, 0.84, -0.205), (0.42, 0.44, 0.06), TD)                    # gluga - spate
    body.box((-0.205, 0.88, -0.02), (0.04, 0.34, 0.42), TD)                # gluga - laterale
    body.box((0.205, 0.88, -0.02), (0.04, 0.34, 0.42), TD)
    body.box((0, 1.10, -0.12), (0.18, 0.12, 0.22), TD)                     # varful glugii
    body.box((0, 0.45, -0.18), (0.50, 0.40, 0.06), TD)                     # pelerina
    body.box((0.12, 0.40, -0.24), (0.14, 0.50, 0.14), LEATHER, rot=(0, 0, 18))   # tolba
    for k in range(3):
        body.box((0.04 + k * 0.05, 0.70 + k * 0.02, -0.24), (0.04, 0.14, 0.04), CLOTH_WHITE, rot=(0, 0, 18))  # pene

    arm_l = MeshBuilder()                                                  # mana cu arcul
    arm_l.box((0, -0.25, 0), (0.15, 0.48, 0.15), T)
    arm_l.box((0, -0.52, 0), (0.13, 0.12, 0.13), SKIN)
    arm_l.box((0, -0.53, 0.08), (0.06, 0.26, 0.06), DARK_LEATHER)         # maner
    arm_l.box((0, -0.25, 0.02), (0.05, 0.42, 0.05), WOOD, rot=(-22, 0, 0))   # brat superior al arcului
    arm_l.box((0, -0.81, 0.02), (0.05, 0.42, 0.05), WOOD, rot=(22, 0, 0))    # brat inferior
    arm_l.box((0, -0.53, -0.07), (0.015, 1.02, 0.015), CLOTH_WHITE)       # coarda

    arm_r = MeshBuilder()
    arm_r.box((0, -0.25, 0), (0.15, 0.48, 0.15), T)
    arm_r.box((0, -0.52, 0), (0.13, 0.12, 0.13), SKIN)

    legs = leg_mesh(LEATHER, DARK_LEATHER)
    return dict(body=body.build(), arm_l=arm_l.build(), arm_r=arm_r.build(), leg_l=legs, leg_r=legs)


def cavalry_models(team):
    T, TD = TEAM_COLORS[team], TEAM_DARK[team]
    horse = MeshBuilder()
    horse.box((0, 1.0, 0), (0.62, 0.58, 1.45), HORSE_COLOR)                # trunchi
    horse.box((0, 1.38, 0.72), (0.32, 0.65, 0.34), HORSE_COLOR, rot=(-30, 0, 0))   # gat
    horse.box((0, 1.72, 0.98), (0.27, 0.28, 0.58), HORSE_COLOR)            # cap
    horse.box((0, 1.66, 1.28), (0.24, 0.22, 0.12), HORSE_DARK)             # bot
    horse.box((-0.09, 1.92, 0.78), (0.06, 0.14, 0.06), HORSE_DARK)         # urechi
    horse.box((0.09, 1.92, 0.78), (0.06, 0.14, 0.06), HORSE_DARK)
    horse.box((-0.14, 1.78, 1.05), (0.02, 0.05, 0.05), BLACK)              # ochi
    horse.box((0.14, 1.78, 1.05), (0.02, 0.05, 0.05), BLACK)
    horse.box((0, 1.55, 0.58), (0.08, 0.6, 0.22), HORSE_DARK, rot=(-30, 0, 0))     # coama
    horse.box((0, 1.0, -0.84), (0.14, 0.55, 0.14), HORSE_DARK, rot=(28, 0, 0))     # coada
    horse.box((0, 0.98, -0.05), (0.68, 0.46, 1.05), T)                     # valtrap (patura echipei)
    horse.box((0, 0.77, -0.05), (0.70, 0.06, 1.07), GOLD)                  # bordura
    horse.box((0, 1.31, -0.05), (0.50, 0.10, 0.55), LEATHER)               # sa
    horse.box((0, 1.68, 1.0), (0.29, 0.05, 0.4), DARK_LEATHER)             # capastru

    rider = MeshBuilder()                                                  # pivot = sa
    rider.box((0, 0.35, 0), (0.46, 0.55, 0.30), STEEL)
    rider.box((0, 0.30, 0.16), (0.28, 0.45, 0.02), T)
    rider.box((0, 0.06, 0), (0.48, 0.07, 0.32), LEATHER)
    rider.box((0, 0.84, 0), (0.34, 0.34, 0.34), SKIN)
    rider.box((0, 0.88, 0), (0.40, 0.42, 0.40), STEEL)                     # coif
    rider.box((0, 0.86, 0.202), (0.28, 0.05, 0.01), BLACK)
    rider.box((0, 1.15, -0.05), (0.07, 0.16, 0.32), T)                     # panas
    for sx in (-1, 1):                                                     # picioare pe lateralele calului
        rider.box((sx * 0.36, -0.02, 0.12), (0.16, 0.16, 0.42), DARK_STEEL)
        rider.box((sx * 0.38, -0.32, 0.26), (0.15, 0.5, 0.16), DARK_STEEL)
        rider.box((sx * 0.38, -0.58, 0.32), (0.16, 0.10, 0.24), DARK_LEATHER)
    rider.box((-0.3, 0.32, 0.12), (0.14, 0.42, 0.14), DARK_STEEL)          # brat stang
    rider.box((-0.40, 0.25, 0.18), (0.04, 0.6, 0.48), DARK_STEEL)          # scut
    rider.box((-0.425, 0.25, 0.18), (0.03, 0.52, 0.40), T)
    rider.box((-0.445, 0.28, 0.18), (0.02, 0.22, 0.07), GOLD)
    rider.box((0.3, 0.30, 0.12), (0.14, 0.42, 0.14), DARK_STEEL)           # brat drept
    rider.box((0.34, 0.15, 0.55), (0.07, 0.07, 2.9), WOOD)                 # lance
    rider.box((0.34, 0.15, 2.08), (0.05, 0.05, 0.3), STEEL)                # varf
    rider.box((0.34, 0.15, 0.35), (0.14, 0.14, 0.12), DARK_STEEL)          # aparatoare
    rider.box((0.34, 0.27, 1.6), (0.01, 0.18, 0.36), T)                    # fanion

    leg = MeshBuilder()
    leg.box((0, -0.36, 0), (0.15, 0.72, 0.17), HORSE_COLOR)
    leg.box((0, -0.72, 0.02), (0.17, 0.08, 0.2), HORSE_DARK)               # copita
    legm = leg.build()
    return dict(body=horse.build(), rider=rider.build(), leg=legm)


def shadow_mesh(radius):
    def make():
        mb = MeshBuilder()
        mb.disc((0, 0, 0), radius, rgb(0, 0, 0, 0.3), sides=10)
        return mb.build()
    return cached(('shadow', radius), make)


def arrow_mesh():
    def make():
        mb = MeshBuilder()
        mb.box((0, 0, 0), (0.035, 0.035, 0.75), WOOD)
        mb.box((0, 0, 0.4), (0.07, 0.07, 0.1), STEEL)
        mb.box((0, 0, -0.32), (0.01, 0.12, 0.12), CLOTH_WHITE)
        mb.box((0, 0, -0.32), (0.12, 0.01, 0.12), CLOTH_WHITE)
        return mb.build()
    return cached('arrow', make)


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


# ================================================================ PROIECTIL
class Projectile:
    """Sageata care zboara in arc spre tinta (fara coliziuni: loveste la final de zbor)."""
    SPEED = 16

    def __init__(self, x, y, z, target, damage):
        self.sx, self.sy, self.sz = x, y, z
        self.target = target
        self.damage = damage
        dist = math.hypot(target.x - x, target.z - z)
        self.duration = max(0.15, dist / self.SPEED)
        self.arc = dist * 0.12
        self.t = 0
        self.node = attach_mesh(manager.fx_root, arrow_mesh(), 'arrow')
        self.node.setPos(x, y, z)
        self.alive = True

    def update(self, dt):
        tgt = self.target
        self.t += dt
        s = min(1.0, self.t / self.duration)
        ex, ey, ez = tgt.x, tgt.y + 1.0, tgt.z
        x = self.sx + (ex - self.sx) * s
        z = self.sz + (ez - self.sz) * s
        y = self.sy + (ey - self.sy) * s + 4 * self.arc * s * (1 - s)
        self.node.lookAt(x, y, z)          # orientare dupa directia de zbor
        self.node.setPos(x, y, z)
        if s >= 1:
            if not tgt.is_dead:
                tgt.knockback(tgt.x - self.sx, tgt.z - self.sz, 0.35)
                tgt.take_damage(self.damage)
            self.remove()
        elif tgt.is_dead and s > 0.8:
            self.remove()

    def remove(self):
        self.alive = False
        self.node.removeNode()


# ================================================================ UNITATE DE BAZA
class Unit:
    """Clasa Python simpla (nu Entity): logica nu mai trece prin __setattr__ din Ursina."""
    STATS = dict(hp=100, speed=3, attack_range=1.5, attack_damage=10,
                 attack_cooldown=1.0, radius=BASE_RADIUS)
    ATTACK_SOUND = 'sabie.wav'
    BAR_HEIGHT = 2.05
    HIP_Y = 0.72
    SHADOW = 0.5

    def __init__(self, x, z, team):
        stats = self.STATS
        self.team = team
        self.hp = self.max_hp = stats['hp']
        self.speed = stats['speed']
        self.attack_range = stats['attack_range']
        self.attack_damage = stats['attack_damage']
        self.attack_cooldown = stats['attack_cooldown']
        self.radius = stats['radius']

        self.x, self.z = x, z
        self.y = terrain.height_at(x, z)
        self.heading = math.degrees(math.atan2(-x, -z))      # privim spre centrul arenei
        self.is_dead = False
        self.target_unit = None
        self.attack_timer = random.uniform(0, 0.3)
        self.retarget_timer = random.uniform(0, 0.4)   # decalat, ca sa nu recalculeze toate in acelasi frame
        self.anim_time = random.uniform(0, 10)
        self.flash_timer = 0
        self.swing_time = 0
        self.swing_angle = -100
        self.health_bar = None
        self.health_bar_fg = None
        self.side = random.choice((-1, 1))          # in ce parte ocoleste piedicile
        self.posed = False                          # membrele sunt in afara pozitiei de repaus?

        # Nici macar radacina nu e Entity: Ursina ar face munca in plus pentru ea in fiecare frame.
        # Shader-ul si ceata se mostenesc de la manager.unit_root.
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
        s = random.uniform(0.94, 1.06)                 # mica variatie de marime
        self.body.setScale(s)
        self.body.setY(self.body_base_y)
        self.sync()
        manager.register(self)

    # ---- model -------------------------------------------------------
    def models(self):
        raise NotImplementedError

    def build_model(self):
        m = self.models()
        attach_mesh(self.body, m['body'], 'torso')
        self.arm_l = attach_mesh(self.body, m['arm_l'], 'arm_l')
        self.arm_r = attach_mesh(self.body, m['arm_r'], 'arm_r')
        self.leg_l = attach_mesh(self.body, m['leg_l'], 'leg_l')
        self.leg_r = attach_mesh(self.body, m['leg_r'], 'leg_r')
        self.arm_l.setPos(-0.33, 0.56, 0)
        self.arm_r.setPos(0.33, 0.56, 0)
        self.leg_l.setPos(-0.13, 0.02, 0)
        self.leg_r.setPos(0.13, 0.02, 0)
        # Maini si picioare in antifaza, ca la mersul real
        self.walk_parts = [(self.leg_l, 1, 40), (self.leg_r, -1, 40),
                           (self.arm_l, -1, 35), (self.arm_r, 1, 35)]
        self.swing_part = self.arm_r

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
        if self.swing_time > 0:
            self.swing_time = max(0, self.swing_time - dt)
            self.swing_part.setP(-self.swing_angle * self.swing_time / SWING_DURATION)
        if battling:
            self.think(dt)
            self.sync()
            if self.health_bar is not None:
                self.health_bar.setPos(self.x, self.y + self.BAR_HEIGHT, self.z)

    def think(self, dt):
        self.separate(dt)

        # Retintim periodic, nu in fiecare frame
        self.retarget_timer -= dt
        target = self.target_unit
        if target is None or target.is_dead or self.retarget_timer <= 0:
            target = self.target_unit = manager.closest_enemy(self)
            self.retarget_timer = random.uniform(0.3, 0.6)

        if target is None:
            self.animate_idle(dt)
            return

        dx, dz = target.x - self.x, target.z - self.z
        dist = math.hypot(dx, dz)
        reach = self.attack_range + (target.radius - BASE_RADIUS)

        if dist > 0.001:
            self.face(dx, dz, dt)

        if dist > reach:
            ux, uz = self.avoid_obstacles(dx / dist, dz / dist)
            step = self.speed * dt
            if self.y < WATER_Y - 0.05:
                step *= WATER_SLOWDOWN
            self.x = clamp_arena(self.x + ux * step)
            self.z = clamp_arena(self.z + uz * step)
            self.animate_walk(dt)
        else:
            self.animate_combat(dt)
            self.attack_timer += dt
            if self.attack_timer >= self.attack_cooldown:
                self.attack_timer = 0
                self.perform_attack(target)

        self.y = terrain.height_at(self.x, self.z)

    # ---- miscare -----------------------------------------------------
    def face(self, dx, dz, dt):
        target_angle = math.degrees(math.atan2(dx, dz))
        diff = (target_angle - self.heading + 180) % 360 - 180   # drumul cel mai scurt
        self.heading += diff * min(1, TURN_SPEED * dt)

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
        """Coliziune moale cu vecinii (doar celulele din jur) + piedici solide."""
        x, z, rad = self.x, self.z, self.radius
        k = SEPARATION_STRENGTH * dt
        grid = manager.grid
        cx, cz = int(x // CELL_SIZE), int(z // CELL_SIZE)
        neighbours = []
        for i in (cx - 1, cx, cx + 1):
            for j in (cz - 1, cz, cz + 1):
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
            push = (min_dist - dist) * k / dist
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

    def knockback(self, dx, dz, strength):
        length = math.hypot(dx, dz)
        if length == 0:
            return
        self.x = clamp_arena(self.x + dx / length * strength)
        self.z = clamp_arena(self.z + dz / length * strength)

    # ---- animatii ----------------------------------------------------
    def animate_walk(self, dt):
        self.anim_time += dt * self.speed * 3.2
        swing = math.sin(self.anim_time)
        busy = self.swing_part if self.swing_time > 0 else None
        for part, sign, amplitude in self.walk_parts:
            if part is not busy:
                part.setP(swing * sign * amplitude)
        self.body.setY(self.body_base_y + abs(swing) * 0.06)      # mic "balans" la mers
        self.posed = True

    def animate_idle(self, dt, skip=None):
        if not self.posed:                                        # deja in repaus: nimic de facut
            return
        k = min(1, 10 * dt)                                       # revenire lina la pozitia de repaus
        busy = self.swing_part if self.swing_time > 0 else None
        biggest = 0
        for part, _, _ in self.walk_parts:
            if part is not busy and part is not skip:
                p = part.getP() * (1 - k)
                part.setP(p)
                biggest = max(biggest, abs(p))
        y = self.body.getY()
        self.body.setY(y + (self.body_base_y - y) * k)
        if biggest < 0.5 and skip is None and busy is None:
            for part, _, _ in self.walk_parts:
                part.setP(0)
            self.body.setY(self.body_base_y)
            self.posed = False

    def animate_combat(self, dt):
        self.animate_idle(dt)

    # ---- lupta -------------------------------------------------------
    def perform_attack(self, target):
        self.swing_time = SWING_DURATION
        play_sound(self.ATTACK_SOUND)
        self.deliver_attack(target)

    def deliver_attack(self, target):
        """Corp la corp; clasele la distanta suprascriu metoda asta."""
        target.take_damage(self.attack_damage)
        target.knockback(target.x - self.x, target.z - self.z, 0.3)

    def take_damage(self, amount):
        if self.is_dead:
            return
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
        self.root.setColorScale(0.38, 0.38, 0.42, 1)    # corpul se intuneca
        self.remove_health_bar()
        manager.add_corpse(self)

    def remove_health_bar(self):
        if self.health_bar is not None:
            self.health_bar.removeNode()
            self.health_bar = None

    def destroy(self):
        self.remove_health_bar()
        self.root.removeNode()


# ================================================================ UNITATI SPECIFICE
class Knight(Unit):
    STATS = dict(hp=120, speed=3, attack_range=1.5, attack_damage=30,
                 attack_cooldown=1.0, radius=BASE_RADIUS)

    def models(self):
        return cached(('knight', self.team), lambda: knight_models(self.team))


class Archer(Unit):
    STATS = dict(hp=60, speed=2, attack_range=12, attack_damage=15,
                 attack_cooldown=1.5, radius=BASE_RADIUS)
    ATTACK_SOUND = 'sageata.wav'

    def models(self):
        return cached(('archer', self.team), lambda: archer_models(self.team))

    def build_model(self):
        super().build_model()
        self.swing_angle = 60                     # trage coarda cu mana dreapta

    def animate_combat(self, dt):
        # tine arcul ridicat spre inamic cat timp trage
        self.animate_idle(dt, skip=self.arm_l)
        self.posed = True
        p = self.arm_l.getP()
        self.arm_l.setP(p + (80 - p) * min(1, 12 * dt))

    def deliver_attack(self, target):
        h = math.radians(self.heading)
        manager.projectiles.append(
            Projectile(self.x + math.sin(h) * 0.5, self.y + 1.3, self.z + math.cos(h) * 0.5,
                       target, self.attack_damage))


class Cavalry(Unit):
    STATS = dict(hp=200, speed=7, attack_range=2.5, attack_damage=45,
                 attack_cooldown=1.2, radius=1.0)
    BAR_HEIGHT = 2.75
    HIP_Y = 0.0
    SHADOW = 0.95

    def models(self):
        return cached(('cavalry', self.team), lambda: cavalry_models(self.team))

    def build_model(self):
        m = self.models()
        attach_mesh(self.body, m['body'], 'horse')
        legs = []
        for x, z in ((-0.2, 0.55), (0.2, 0.55), (-0.2, -0.55), (0.2, -0.55)):
            leg = attach_mesh(self.body, m['leg'], 'leg')
            leg.setPos(x, 0.78, z)
            legs.append(leg)
        fl, fr, bl, br = legs
        # Diagonalele se misca impreuna (trap)
        self.walk_parts = [(fl, 1, 32), (br, 1, 32), (fr, -1, 32), (bl, -1, 32)]
        self.rider = attach_mesh(self.body, m['rider'], 'rider')
        self.rider.setPos(0, 1.35, -0.05)
        self.swing_part, self.swing_angle = self.rider, 25       # calaretul se apleaca la atac

    def animate_walk(self, dt):
        super().animate_walk(dt)
        if self.swing_time <= 0:
            self.rider.setP(math.sin(self.anim_time * 2) * 3)     # calaretul se legana in sa


# ---------------------------------------------------------------- TIPURI DE UNITATI (tasta -> (nume, clasa))
UNIT_TYPES = {
    '1': ('CAVALER', Knight),
    '2': ('ARCAS', Archer),
    '3': ('CAVALERIE', Cavalry),
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
        self.corpses = []
        self.team_units = {'red': [], 'blue': []}
        self.grid = {}                               # grila spatiala pentru vecini
        self._last_counts = None
        self.message_timer = 0
        self.last_paint = None
        self.water_t = 0

        # Cateva entitati "parinte": toate unitatile/sagetile/barele sunt noduri simple sub ele
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
            text='1: Cavaler | 2: Arcas | 3: Cavalerie || T: Echipa || Z: Anuleaza || SPACE: Start || R: Reset\n'
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
        # "Yeet": viteza + rotatie aleatoare, apoi gravitatie. Animat manual (fara tween-uri).
        unit.vel = [random.uniform(-4, 4), random.uniform(6, 10), random.uniform(-4, 4)]
        unit.spin = (random.uniform(-900, 900), random.uniform(-900, 900), random.uniform(-900, 900))
        unit.corpse_time = 0
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
            for p in self.projectiles:
                p.update(dt)
            self.projectiles = [p for p in self.projectiles if p.alive]

        if self.corpses:
            self.update_corpses(dt)

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

    def update_corpses(self, dt):
        alive = []
        for u in self.corpses:
            u.corpse_time += dt
            if u.corpse_time >= DEATH_DELAY:
                u.destroy()
                continue
            u.vel[1] -= 25 * dt
            u.x += u.vel[0] * dt
            u.y += u.vel[1] * dt
            u.z += u.vel[2] * dt
            u.root.setPos(u.x, u.y, u.z)
            b = u.body
            b.setHpr(b.getH() + u.spin[0] * dt, b.getP() + u.spin[1] * dt, b.getR() + u.spin[2] * dt)
            alive.append(u)
        self.corpses = alive

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
            # "pictare": tinand click stanga, plasam o unitate la fiecare ~1.2 unitati de mers
            if mouse.left and self.last_paint is not None:
                if math.hypot(point.x - self.last_paint[0], point.z - self.last_paint[1]) > 1.2:
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
            name = UNIT_TYPES[self.selected_key][0]
            self.ui_status.text = f'Selectat: {name} | Echipa: {TEAM_NAMES[self.current_team]}'
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
        self.units, self.placed, self.corpses, self.projectiles = [], [], [], []
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
        _, unit_class = UNIT_TYPES[self.selected_key]
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
