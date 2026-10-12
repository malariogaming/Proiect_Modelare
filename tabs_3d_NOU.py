"""
Battle Simulator (Ursina)

Controale:
  1 / 2 / 3     alege unitatea (Cavaler / Arcas / Cavalerie)
  T             schimba echipa
  Click stanga  plaseaza unitatea
  Z             sterge ultima unitate plasata
  SPACE         porneste lupta
  R             reset
  Click dreapta + mouse = roteste camera | Scroll = zoom | Click mijloc = muta camera

Fisiere optionale (langa script): sabie.wav, sageata.wav, muzica.mp3
Daca lipsesc, jocul ruleaza fara sunet.
"""
from ursina import *
from pathlib import Path
import math
import random
import time as pytime  # 'time' din ursina contine time.dt, deci folosim alt alias

app = Ursina()
window.title = 'Battle Simulator'

# ---------------------------------------------------------------- CONSTANTE
ARENA_HALF = 19             # jumatate din teren (40x40) minus o margine
CELL_SIZE = 2.0             # celula grilei spatiale (>= suma maxima a razelor)
BASE_RADIUS = 0.5           # raza unei unitati "normale"
SEPARATION_STRENGTH = 4     # cat de tare se imping unitatile intre ele
TURN_SPEED = 12             # viteza de rotire spre inamic
SWING_DURATION = 0.3        # durata animatiei de atac
DEATH_DELAY = 1.5           # dupa cat timp dispare cadavrul

TEAM_COLORS = {'red': color.red, 'blue': color.blue}
TEAM_NAMES = {'red': 'ROSIE', 'blue': 'ALBASTRA'}

# hsv(h, s, v) are acelasi sens in toate versiunile Ursina, spre deosebire de
# color.rgb(), care a trecut de la 0-255 la 0-1 intre versiuni.
HORSE_COLOR = color.hsv(25, 0.86, 0.55)
HORSE_HEAD_COLOR = color.hsv(22, 0.92, 0.47)


def clamp_arena(value):
    return max(-ARENA_HALF, min(ARENA_HALF, value))


def iter_descendants(entity):
    """Toti copiii (recursiv) - entity.children da doar nivelul direct."""
    for child in entity.children:
        yield child
        yield from iter_descendants(child)


# ---------------------------------------------------------------- SUNET
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
    """Reda un sunet scurt. Entitatea Audio se autodistruge (altfel se aduna la infinit)
    si sunetele identice sunt limitate in timp, ca sa nu se transforme in zgomot."""
    if not sound_available(name):
        return
    now = pytime.monotonic()
    if now - _last_played.get(name, 0) < min_interval:
        return
    _last_played[name] = now
    Audio(name, autoplay=True, auto_destroy=True, volume=volume)


# ---------------------------------------------------------------- PROIECTIL
class Projectile(Entity):
    SPEED = 15
    HIT_RADIUS = 0.6
    MAX_LIFETIME = 4

    def __init__(self, position, target, damage, **kwargs):
        super().__init__(model='cube', scale=(0.05, 0.05, 0.6), color=color.black,
                         position=position, **kwargs)
        self.target = target
        self.damage = damage
        self.age = 0
        self.look_at(self.aim_point())

    def aim_point(self):
        # tinta la nivelul pieptului, nu la picioare
        return Vec3(self.target.x, self.target.y + 1.0, self.target.z)

    def update(self):
        self.age += time.dt
        if self.target.is_dead or self.age > self.MAX_LIFETIME:
            destroy(self)
            return

        aim = self.aim_point()
        to_target = aim - self.position
        dist = to_target.length()

        if dist < self.HIT_RADIUS:
            self.target.knockback(to_target, 0.4)
            self.target.take_damage(self.damage)
            destroy(self)
            return

        self.position += (to_target / dist) * self.SPEED * time.dt
        self.look_at(aim)


# ---------------------------------------------------------------- UNITATE DE BAZA
class Unit(Entity):
    STATS = dict(hp=100, speed=3, attack_range=1.5, attack_damage=10,
                 attack_cooldown=1.0, radius=BASE_RADIUS)
    ATTACK_SOUND = 'sabie.wav'
    BAR_HEIGHT = 1.8

    def __init__(self, position, team):
        # Baza e doar un "container" invizibil: fara model si fara collider
        # (un collider ar bloca click-urile de plasare peste alte unitati).
        super().__init__(position=position)
        stats = self.STATS
        self.team = team
        self.team_color = TEAM_COLORS[team]
        self.hp = self.max_hp = stats['hp']
        self.speed = stats['speed']
        self.attack_range = stats['attack_range']
        self.attack_damage = stats['attack_damage']
        self.attack_cooldown = stats['attack_cooldown']
        self.radius = stats['radius']

        self.is_dead = False
        self.target_unit = None
        self.attack_timer = random.uniform(0, 0.3)
        self.retarget_timer = random.uniform(0, 0.4)   # decalat, ca sa nu recalculeze toate in acelasi frame
        self.anim_time = random.uniform(0, 10)
        self.flash_timer = 0
        self.swing_time = 0
        self.health_bar_bg = None
        self.health_bar_fg = None

        self.walk_parts = []        # (parte, semn, amplitudine)
        self.body_base_y = 0.1
        self.swing_part = None
        self.swing_angle = 0
        self.build_model()
        manager.register(self)

    # ---- model -------------------------------------------------------
    def build_model(self):
        c = self.team_color
        self.body = Entity(parent=self, y=self.body_base_y)
        self.head = Entity(parent=self.body, model='sphere', color=c, scale=0.5, y=1.2)
        self.torso = Entity(parent=self.body, model='cube', color=c, scale=(0.5, 0.6, 0.3), y=0.6)

        # origin=(0, 0.5, 0) muta "balamaua" sus (umar / sold)
        def limb(w_h, pos):
            return Entity(parent=self.body, model='cube', color=c, scale=(0.15, w_h, 0.15),
                          position=pos, origin=(0, 0.5, 0))

        self.arm_l = limb(0.5, (-0.35, 0.8, 0))
        self.arm_r = limb(0.5, (0.35, 0.8, 0))
        self.leg_l = limb(0.6, (-0.15, 0.3, 0))
        self.leg_r = limb(0.6, (0.15, 0.3, 0))

        # Maini si picioare in antifaza, ca la mersul real
        self.walk_parts = [(self.leg_l, 1, 45), (self.leg_r, -1, 45),
                           (self.arm_l, -1, 45), (self.arm_r, 1, 45)]
        self.swing_part, self.swing_angle = self.arm_r, -100

    # ---- bucla principala ---------------------------------------------
    def update(self):
        if self.is_dead:
            return
        dt = time.dt
        self.tick_effects(dt)
        if not manager.is_battling or manager.game_over:
            return
        self.think(dt)

    def tick_effects(self, dt):
        # clipire alba la lovitura (fara tween, ca sa nu se bata cu culoarea gri de la moarte)
        if self.flash_timer > 0:
            self.flash_timer -= dt
            if self.flash_timer <= 0:
                self.head.color = self.team_color
        # animatia de atac
        if self.swing_time > 0:
            self.swing_time = max(0, self.swing_time - dt)
            self.swing_part.rotation_x = self.swing_angle * self.swing_time / SWING_DURATION

    def think(self, dt):
        self.separate(dt)

        # Retintim periodic, nu in fiecare frame (mai rapid si mai putin "nervos")
        self.retarget_timer -= dt
        if self.target_unit is None or self.target_unit.is_dead or self.retarget_timer <= 0:
            self.target_unit = manager.closest_enemy(self)
            self.retarget_timer = random.uniform(0.3, 0.6)

        target = self.target_unit
        if target is None:
            self.animate_idle(dt)
            return

        dx, dz = target.x - self.x, target.z - self.z
        dist = math.hypot(dx, dz)
        # raza tintei conteaza: calaretii sunt mai "lati", deci ii atingem de ceva mai departe
        reach = self.attack_range + (target.radius - BASE_RADIUS)

        if dist > 0.001:
            self.face(dx, dz, dt)

        if dist > reach:
            step = self.speed * dt
            self.x = clamp_arena(self.x + dx / dist * step)
            self.z = clamp_arena(self.z + dz / dist * step)
            self.animate_walk(dt)
        else:
            self.animate_idle(dt)
            self.attack_timer += dt
            if self.attack_timer >= self.attack_cooldown:
                self.attack_timer = 0
                self.perform_attack(target)

    # ---- miscare -----------------------------------------------------
    def face(self, dx, dz, dt):
        """Rotire lina spre inamic, doar pe axa Y (fara look_at + resetat rotation_x)."""
        target_angle = math.degrees(math.atan2(dx, dz))
        diff = (target_angle - self.rotation_y + 180) % 360 - 180   # drumul cel mai scurt
        self.rotation_y += diff * min(1, TURN_SPEED * dt)

    def separate(self, dt):
        """Coliziune moale: ne departam de vecinii prea apropiati (doar celulele din jur)."""
        for other in manager.nearby(self):
            if other is self or other.is_dead:
                continue
            dx, dz = self.x - other.x, self.z - other.z
            dist_sq = dx * dx + dz * dz
            min_dist = self.radius + other.radius
            if dist_sq >= min_dist * min_dist:
                continue
            if dist_sq < 1e-6:                      # exact una peste alta -> impingere aleatoare
                dx, dz, dist_sq = random.uniform(-1, 1), random.uniform(-1, 1), 1
            dist = math.sqrt(dist_sq)
            push = (min_dist - dist) * SEPARATION_STRENGTH * dt / dist
            self.x = clamp_arena(self.x + dx * push)
            self.z = clamp_arena(self.z + dz * push)

    def knockback(self, direction, strength):
        length = math.hypot(direction.x, direction.z)
        if length == 0:
            return
        self.x = clamp_arena(self.x + direction.x / length * strength)
        self.z = clamp_arena(self.z + direction.z / length * strength)

    # ---- animatii ----------------------------------------------------
    def animate_walk(self, dt):
        self.anim_time += dt * self.speed * 4
        swing = math.sin(self.anim_time)
        for part, sign, amplitude in self.walk_parts:
            if part is self.swing_part and self.swing_time > 0:
                continue
            part.rotation_x = swing * sign * amplitude
        self.body.y = self.body_base_y + abs(swing) * 0.05      # mic "balans" la mers

    def animate_idle(self, dt):
        k = min(1, 10 * dt)                                      # revenire lina la pozitia de repaus
        for part, _, _ in self.walk_parts:
            if part is self.swing_part and self.swing_time > 0:
                continue
            part.rotation_x -= part.rotation_x * k
        self.body.y += (self.body_base_y - self.body.y) * k

    # ---- lupta -------------------------------------------------------
    def perform_attack(self, target):
        self.swing_time = SWING_DURATION
        play_sound(self.ATTACK_SOUND)
        self.deliver_attack(target)

    def deliver_attack(self, target):
        """Corp la corp; clasele la distanta suprascriu metoda asta."""
        target.take_damage(self.attack_damage)
        target.knockback(Vec3(target.x - self.x, 0, target.z - self.z), 0.3)

    def take_damage(self, amount):
        if self.is_dead:
            return
        self.hp -= amount
        if self.hp <= 0:
            self.die()
            return
        self.head.color = color.white
        self.flash_timer = 0.1
        self.update_health_bar()

    def update_health_bar(self):
        if self.health_bar_bg is None:     # apare doar dupa prima lovitura
            self.health_bar_bg = Entity(parent=self, model='quad', color=color.black,
                                        scale=(1, 0.12), y=self.BAR_HEIGHT, billboard=True)
            self.health_bar_fg = Entity(parent=self.health_bar_bg, model='quad',
                                        origin_x=-0.5, x=-0.5, z=-0.01, scale=(1, 0.8))
        ratio = max(self.hp, 0) / self.max_hp
        self.health_bar_fg.scale_x = ratio
        self.health_bar_fg.color = color.hsv(120 * ratio, 0.85, 0.9)   # verde -> rosu

    def die(self):
        self.is_dead = True
        manager.unregister(self)

        # Tot corpul devine gri (inclusiv casca, sabia etc. - recursiv)
        for part in iter_descendants(self):
            part.color = color.gray
        if self.health_bar_bg:
            destroy(self.health_bar_bg)
            self.health_bar_bg = None

        # Yeet effect
        jump_target = self.position + Vec3(random.uniform(-4, 4), random.uniform(3, 7), random.uniform(-4, 4))
        spin_target = Vec3(random.randint(360, 1080), random.randint(360, 1080), random.randint(360, 1080))
        self.animate_position(jump_target, duration=0.8, curve=curve.out_expo)
        self.body.animate_rotation(spin_target, duration=0.8)
        destroy(self, delay=DEATH_DELAY)


# ---------------------------------------------------------------- UNITATI SPECIFICE
class Knight(Unit):
    STATS = dict(hp=120, speed=3, attack_range=1.5, attack_damage=30,
                 attack_cooldown=1.0, radius=BASE_RADIUS)

    def build_model(self):
        super().build_model()
        Entity(parent=self.head, model='cube', color=color.dark_gray,
               scale=(1.1, 0.4, 1.1), position=(0, 0.2, 0))                    # Casca
        Entity(parent=self.arm_r, model='cube', color=color.light_gray,
               scale=(0.5, 1.5, 1.0), position=(0, -0.6, 0.5))                 # Sabia


class Archer(Unit):
    STATS = dict(hp=60, speed=2, attack_range=12, attack_damage=15,
                 attack_cooldown=1.5, radius=BASE_RADIUS)
    ATTACK_SOUND = 'sageata.wav'

    def build_model(self):
        super().build_model()
        Entity(parent=self.head, model='cube', color=color.black,
               scale=(0.9, 0.3, 0.3), position=(0, 0.1, 0.4))                  # Ochelari
        Entity(parent=self.arm_l, model='cube', color=color.brown,
               scale=(0.5, 2.0, 0.5), position=(0, -0.4, 0.5))                 # Arcul
        self.swing_angle = -60                                                 # "intinde" arcul cu mana dreapta

    def deliver_attack(self, target):
        Projectile(position=Vec3(self.x, self.y + 1.2, self.z), target=target,
                   damage=self.attack_damage)


class Cavalry(Unit):
    STATS = dict(hp=200, speed=7, attack_range=2.5, attack_damage=45,
                 attack_cooldown=1.2, radius=1.0)
    BAR_HEIGHT = 2.5

    def build_model(self):
        # Inlocuim omuletul cu CAL + CALARET
        self.body_base_y = 0
        self.body = Entity(parent=self, y=self.body_base_y)

        self.horse_body = Entity(parent=self.body, model='cube', color=HORSE_COLOR,
                                 scale=(0.8, 0.7, 1.6), y=0.7)
        self.horse_head = Entity(parent=self.horse_body, model='cube', color=HORSE_HEAD_COLOR,
                                 scale=(0.4, 0.6, 0.4), position=(0, 0.5, 0.6))

        def leg(x, z):
            return Entity(parent=self.body, model='cube', color=HORSE_HEAD_COLOR,
                          scale=(0.15, 0.6, 0.15), position=(x, 0.3, z), origin=(0, 0.5, 0))

        self.leg_fl, self.leg_fr = leg(-0.3, 0.6), leg(0.3, 0.6)
        self.leg_bl, self.leg_br = leg(-0.3, -0.6), leg(0.3, -0.6)
        # Diagonalele se misca impreuna (trap)
        self.walk_parts = [(self.leg_fl, 1, 30), (self.leg_br, 1, 30),
                           (self.leg_fr, -1, 30), (self.leg_bl, -1, 30)]

        self.rider = Entity(parent=self.body, y=1.2, z=-0.2)
        self.head = Entity(parent=self.rider, model='sphere', color=self.team_color, scale=0.4, y=0.5)
        Entity(parent=self.rider, model='cube', color=self.team_color, scale=(0.4, 0.5, 0.3), y=0.1)
        Entity(parent=self.rider, model='cube', color=color.light_gray,
               scale=(0.05, 0.05, 2.5), position=(0.4, 0.2, 1.0))              # Sulita

        self.swing_part, self.swing_angle = self.rider, 25                     # calaretul se apleaca la atac


# ---------------------------------------------------------------- TIPURI DE UNITATI (tasta -> (nume, clasa))
UNIT_TYPES = {
    '1': ('CAVALER', Knight),
    '2': ('ARCAS', Archer),
    '3': ('CAVALERIE', Cavalry),
}


# ---------------------------------------------------------------- MANAGER
class BattleManager(Entity):
    def __init__(self):
        super().__init__()
        self.is_battling = False
        self.game_over = False
        self.current_team = 'red'
        self.selected_key = '1'

        self.units = []                              # doar unitatile in viata
        self.team_units = {'red': [], 'blue': []}
        self.grid = {}                               # grila spatiala pentru vecini
        self._last_counts = None
        self.message_timer = 0

        self.ground = Entity(model='plane', scale=(40, 1, 40), color=color.green.tint(-0.2), collider='box')
        self.cursor = Entity(model='plane', scale=1.5, y=0.03, enabled=False)   # previzualizare plasare

        self.ui_status = Text(text='', origin=(0, 0), y=0.45)
        self.ui_controls = Text(
            text='1: Cavaler | 2: Arcas | 3: Cavalerie || T: Echipa || Z: Anuleaza || SPACE: Start || R: Reset\n'
                 'Click dreapta + mouse: camera | Scroll: zoom',
            origin=(0, 0), y=0.40, scale=0.8)
        self.ui_counts = Text(text='', origin=(0, 0), y=0.32)
        self.ui_message = Text(text='', origin=(0, 0), y=0.25, scale=1.2, color=color.yellow)
        self.ui_victory = Text(text='', origin=(0, 0), y=0.1, scale=3)
        self.update_ui()

    # ---- registru unitati --------------------------------------------
    def register(self, unit):
        self.units.append(unit)

    def unregister(self, unit):
        if unit in self.units:
            self.units.remove(unit)

    def count(self, team):
        return sum(1 for u in self.units if u.team == team)

    def refresh_battlefield(self):
        """O data pe frame: liste pe echipe + grila spatiala. Unitatile nu mai scaneaza scene.entities."""
        self.team_units = {'red': [], 'blue': []}
        self.grid = {}
        for u in self.units:
            if u.is_dead:
                continue
            self.team_units[u.team].append(u)
            cell = (int(u.x // CELL_SIZE), int(u.z // CELL_SIZE))
            self.grid.setdefault(cell, []).append(u)

    def nearby(self, unit):
        cx, cz = int(unit.x // CELL_SIZE), int(unit.z // CELL_SIZE)
        for i in (cx - 1, cx, cx + 1):
            for j in (cz - 1, cz, cz + 1):
                yield from self.grid.get((i, j), ())

    def closest_enemy(self, unit):
        enemies = self.team_units['blue' if unit.team == 'red' else 'red']
        best, best_d = None, float('inf')
        for e in enemies:
            if e.is_dead:
                continue
            d = (e.x - unit.x) ** 2 + (e.z - unit.z) ** 2
            if d < best_d:
                best, best_d = e, d
        return best

    # ---- bucla -------------------------------------------------------
    def update(self):
        self.update_cursor()
        self.refresh_battlefield()
        self.update_counts()

        if self.message_timer > 0:
            self.message_timer -= time.dt
            if self.message_timer <= 0:
                self.ui_message.text = ''

        if not self.is_battling or self.game_over:
            return

        red_alive = len(self.team_units['red'])
        blue_alive = len(self.team_units['blue'])
        if red_alive == 0 and blue_alive > 0:
            self.declare_winner('ALBASTRA', color.blue)
        elif blue_alive == 0 and red_alive > 0:
            self.declare_winner('ROSIE', color.red)
        elif red_alive == 0 and blue_alive == 0:
            self.declare_winner('EGALITATE', color.gray)

    def update_cursor(self):
        point = mouse.world_point
        show = (not self.is_battling) and mouse.hovered_entity == self.ground and point is not None
        self.cursor.enabled = show
        if show:
            self.cursor.x, self.cursor.z = clamp_arena(point.x), clamp_arena(point.z)

    def update_counts(self):
        counts = (self.count('red'), self.count('blue'))
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
        self.cursor.color = TEAM_COLORS[self.current_team]
        self.cursor.alpha = 0.5

    def declare_winner(self, winner_name, win_color):
        self.game_over = True
        self.ui_victory.text = f"ECHIPA {winner_name} A CASTIGAT!\nApasa 'R' pentru Restart"
        self.ui_victory.color = win_color
        self.update_ui()

    # ---- actiuni -----------------------------------------------------
    def start_battle(self):
        if self.count('red') == 0 or self.count('blue') == 0:
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
        for unit in list(self.units):
            destroy(unit)
        self.units.clear()
        for e in list(scene.entities):               # copie, ca sa nu modificam lista in timp ce o parcurgem
            if isinstance(e, Projectile):
                destroy(e)
        self.is_battling = False
        self.game_over = False
        self.ui_victory.text = ''
        self.ui_message.text = ''
        if hasattr(self, 'bg_music'):
            self.bg_music.pause()
        self.update_ui()

    def place_unit(self):
        point = mouse.world_point
        if point is None:
            return
        _, unit_class = UNIT_TYPES[self.selected_key]
        unit_class(position=(clamp_arena(point.x), 0.1, clamp_arena(point.z)), team=self.current_team)

    def input(self, key):
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
        elif key == 'z' and self.units:
            destroy(self.units.pop())
        elif key == 'left mouse down' and mouse.hovered_entity == self.ground:
            self.place_unit()
        self.update_ui()


manager = BattleManager()
Sky()
editor_camera = EditorCamera()
editor_camera.rotation_x = 45       # privim de sus, nu de la nivelul solului
editor_camera.target_z = -35        # putin mai departe, ca sa incapa tot terenul

app.run()